"""Read-only parsing of Unity Animator Controller (``.controller``) files.

Backs the Animation Bug Detection and State Machine Sanity Check use-cases
(Phase I, section 8). Same philosophy as ``connectors.unity_scan``: Unity's
``.controller`` files are YAML-ish text (a multi-document stream, each
document a separate serialized object introduced by a ``--- !u!<classID>
&<fileID>`` anchor line), and a full YAML parser isn't needed -- targeted
regex extraction of the handful of fields this module cares about is
sufficient and matches the rest of the codebase's established approach.

**Format verification.** Unlike most of this codebase's regex-parsed Unity
file formats, ``.controller`` structure wasn't already established anywhere
in this project, and no real Unity project was available in this environment
to generate one. The field names and layout below were verified against a
real, Unity-generated ``.controller`` file fetched from a public GitHub repo
(TUTOUNITYFR/creer-un-jeu-en-2d-facilement-unity, ``Assets/Animations/Props/
Chest.controller``) -- not merely inferred from documentation. That sample
confirmed: the ``!u!1102`` (AnimatorState) / ``!u!1107``
(AnimatorStateMachine) / ``!u!1101`` (AnimatorStateTransition) class IDs;
that ``m_Motion: {fileID: 0}`` (no ``guid``) means no motion clip is
assigned; that ``m_DstState``/``m_DstStateMachine``/``m_TransitionDuration``/
``m_HasExitTime``/``m_IsExit`` are transition fields at exactly 2-space
top-level indent; and that ``m_ChildStates`` entries nest their state
reference under ``m_State: {fileID: ...}``.

**What is NOT independently verified**: the sample had no nested
sub-state-machines, so ``m_ChildStateMachines``/``m_EntryTransitions`` field
presence is confirmed but their exact usage (how entry into a nested state
machine is represented) is not exercised by the sample and is not relied on
by this module's reachability logic -- see ``AnimationStateMachine
CheckService`` in ``core.animation_state_machine_check``, which treats every
parsed state machine's own ``m_DefaultState`` as independently reachable
rather than trying to resolve nested-entry edges, precisely to avoid
asserting something about the nested-SM wire format this project has not
confirmed against a real sample. ``AnimatorTransition`` (state-machine-to-
state-machine transitions, as opposed to ``AnimatorStateTransition``) is
assumed to share class ID ``1101`` based on general Unity documentation, not
a sample containing one.

Every function here only reads files; nothing is ever modified or deleted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from spiced.connectors.unity_scan import iter_assets

_ANCHOR_RE = re.compile(r"^--- !u!(\d+) &(-?\d+)\s*$")
_TYPE_NAME_RE = re.compile(r"^(\w+):\s*$")
_FILEID_RE = re.compile(r"fileID:\s*(-?\d+)")

_STATE_TYPE = "AnimatorState"
_STATE_MACHINE_TYPE = "AnimatorStateMachine"
_STATE_TRANSITION_TYPE = "AnimatorStateTransition"
_TRANSITION_TYPE = "AnimatorTransition"


@dataclass(frozen=True)
class ParsedAnimatorState:
    file_id: str
    name: str | None
    has_motion: bool
    transition_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedAnimatorStateMachine:
    file_id: str
    name: str | None
    default_state_id: str | None
    child_state_ids: list[str] = field(default_factory=list)
    child_state_machine_ids: list[str] = field(default_factory=list)
    any_state_transition_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedAnimatorTransition:
    file_id: str
    kind: str  # "AnimatorStateTransition" | "AnimatorTransition"
    dst_state_id: str | None  # None (or "0") means no state target
    dst_state_machine_id: str | None
    transition_duration: float | None
    has_exit_time: bool | None
    is_exit: bool | None


@dataclass(frozen=True)
class ParsedController:
    path: str  # relative to the project root, forward-slashed
    states: dict[str, ParsedAnimatorState] = field(default_factory=dict)
    state_machines: dict[str, ParsedAnimatorStateMachine] = field(default_factory=dict)
    transitions: dict[str, ParsedAnimatorTransition] = field(default_factory=dict)


def _split_documents(text: str) -> list[tuple[str, str, list[str]]]:
    """Split a ``.controller`` file into ``(type_name, file_id, body_lines)``
    per YAML document. ``type_name`` is the unindented ``SomeType:`` line
    immediately following the ``--- !u!<classID> &<fileID>`` anchor (e.g.
    ``AnimatorState``); ``body_lines`` excludes both the anchor and that
    type-name line. Anything before the first anchor (the ``%YAML``/``%TAG``
    header) is discarded.
    """
    docs: list[tuple[str, str, list[str]]] = []
    file_id: str | None = None
    buf: list[str] = []

    def _flush() -> None:
        if file_id is None:
            return
        type_name = None
        body = buf
        if buf:
            m = _TYPE_NAME_RE.match(buf[0])
            if m:
                type_name = m.group(1)
                body = buf[1:]
        docs.append((type_name or "", file_id, body))

    for line in text.splitlines():
        m = _ANCHOR_RE.match(line)
        if m:
            _flush()
            file_id = m.group(2)
            buf = []
            continue
        buf.append(line)
    _flush()
    return docs


def _top_field_raw(lines: list[str], field_name: str) -> str | None:
    """The raw value text of a top-level (exactly 2-space-indented) field."""
    pattern = re.compile(rf"^  {re.escape(field_name)}:\s*(.*)$")
    for line in lines:
        m = pattern.match(line)
        if m:
            return m.group(1).strip()
    return None


def _top_field_fileid(lines: list[str], field_name: str) -> str | None:
    raw = _top_field_raw(lines, field_name)
    if raw is None:
        return None
    m = _FILEID_RE.search(raw)
    return m.group(1) if m else None


def _section_lines(lines: list[str], field_name: str) -> list[str]:
    """Lines belonging to a top-level list/mapping field's block: the header
    line plus any more-indented or list-continuation (``- ...``) lines that
    follow, stopping at the next line whose indent is <= the header's own and
    that isn't itself a list item."""
    out: list[str] = []
    capturing = False
    header_indent = 0
    header_re = re.compile(rf"^(\s*){re.escape(field_name)}:(.*)$")
    for line in lines:
        if not capturing:
            m = header_re.match(line)
            if m:
                capturing = True
                header_indent = len(m.group(1))
                out.append(line)
            continue
        if not line.strip():
            out.append(line)
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= header_indent and not line.lstrip().startswith("-"):
            break
        out.append(line)
    return out


def _parse_state(file_id: str, lines: list[str]) -> ParsedAnimatorState:
    name = _top_field_raw(lines, "m_Name")
    motion_id = _top_field_fileid(lines, "m_Motion")
    has_motion = motion_id is not None and motion_id != "0"
    transitions_section = _section_lines(lines, "m_Transitions")
    transition_ids = _FILEID_RE.findall("\n".join(transitions_section))
    return ParsedAnimatorState(
        file_id=file_id, name=name, has_motion=has_motion, transition_ids=transition_ids
    )


def _parse_state_machine(file_id: str, lines: list[str]) -> ParsedAnimatorStateMachine:
    name = _top_field_raw(lines, "m_Name")
    default_state_id = _top_field_fileid(lines, "m_DefaultState")

    child_states_section = _section_lines(lines, "m_ChildStates")
    child_state_ids = re.findall(r"m_State:\s*\{fileID:\s*(-?\d+)", "\n".join(child_states_section))

    child_sms_section = _section_lines(lines, "m_ChildStateMachines")
    child_sm_ids = re.findall(
        r"m_StateMachine:\s*\{fileID:\s*(-?\d+)", "\n".join(child_sms_section)
    )

    any_state_section = _section_lines(lines, "m_AnyStateTransitions")
    any_state_ids = _FILEID_RE.findall("\n".join(any_state_section))

    return ParsedAnimatorStateMachine(
        file_id=file_id,
        name=name,
        default_state_id=default_state_id,
        child_state_ids=child_state_ids,
        child_state_machine_ids=child_sm_ids,
        any_state_transition_ids=any_state_ids,
    )


def _parse_transition(file_id: str, kind: str, lines: list[str]) -> ParsedAnimatorTransition:
    dst_state_id = _top_field_fileid(lines, "m_DstState")
    dst_state_machine_id = _top_field_fileid(lines, "m_DstStateMachine")

    duration_raw = _top_field_raw(lines, "m_TransitionDuration")
    duration = None
    if duration_raw:
        try:
            duration = float(duration_raw)
        except ValueError:
            duration = None

    has_exit_raw = _top_field_raw(lines, "m_HasExitTime")
    has_exit_time = has_exit_raw == "1" if has_exit_raw is not None else None

    is_exit_raw = _top_field_raw(lines, "m_IsExit")
    is_exit = is_exit_raw == "1" if is_exit_raw is not None else None

    return ParsedAnimatorTransition(
        file_id=file_id,
        kind=kind,
        dst_state_id=dst_state_id,
        dst_state_machine_id=dst_state_machine_id,
        transition_duration=duration,
        has_exit_time=has_exit_time,
        is_exit=is_exit,
    )


def parse_controller_text(text: str, rel_path: str) -> ParsedController:
    """Parse one ``.controller`` file's text into states/state
    machines/transitions, keyed by their Unity ``fileID`` (as a string, since
    IDs can be negative and are never arithmetic in this module)."""
    states: dict[str, ParsedAnimatorState] = {}
    state_machines: dict[str, ParsedAnimatorStateMachine] = {}
    transitions: dict[str, ParsedAnimatorTransition] = {}

    for type_name, file_id, lines in _split_documents(text):
        if type_name == _STATE_TYPE:
            states[file_id] = _parse_state(file_id, lines)
        elif type_name == _STATE_MACHINE_TYPE:
            state_machines[file_id] = _parse_state_machine(file_id, lines)
        elif type_name in (_STATE_TRANSITION_TYPE, _TRANSITION_TYPE):
            transitions[file_id] = _parse_transition(file_id, type_name, lines)
        # Other object types (AnimatorController, StateMachineBehaviour, ...)
        # aren't needed for the bug-detection / sanity-check use cases.

    return ParsedController(
        path=rel_path, states=states, state_machines=state_machines, transitions=transitions
    )


def scan_controllers(project_path: str | Path) -> list[ParsedController]:
    """Parse every ``.controller`` file under the project's ``Assets/``
    folder. Returns ``[]`` (never raises) if the project has no ``Assets/``
    folder or a file can't be read -- unreadable files are silently skipped,
    same discipline as ``connectors.unity_docs_scan.scan_scripts``."""
    root = Path(project_path)
    results: list[ParsedController] = []
    for asset in iter_assets(root):
        if asset.suffix.lower() != ".controller":
            continue
        try:
            text = asset.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = asset.relative_to(root).as_posix()
        results.append(parse_controller_text(text, rel))
    return results
