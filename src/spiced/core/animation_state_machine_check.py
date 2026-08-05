"""State Machine Sanity Check (Phase I, section 8, Phase 2 tier).

The more rigorously verifiable sibling of Animation Bug Detection
(``core.animation_bug_detection``): rather than inferring a *risk* from
structure, this parses the same ``.controller`` files
(``connectors.unity_controller_scan`` -- see its docstring for exactly what
was verified against a real Unity-generated sample) for genuine, verifiable
structural problems, the same "real static analysis" spirit as Dead
Reference Detection:

1. **Unreachable states** -- a state with no incoming transition from any
   other state, from "Any State," or from being a state machine's own
   default/entry state. Unity will never enter such a state at runtime
   (barring a script calling ``Animator.Play``/``CrossFade`` directly by
   name, which this static scan has no way to see -- see the caveat).
2. **Missing transition targets** -- a transition whose ``m_DstState`` or
   ``m_DstStateMachine`` ``fileID`` doesn't match any state/state machine
   actually present in the file. In a well-formed, un-corrupted Unity
   project this shouldn't normally happen (Unity's own editor keeps these in
   sync) -- when it does, it usually means the ``.controller`` file was hand
   -edited, merge-conflicted, or partially corrupted.

**Reachability scope note**: this treats every parsed ``AnimatorStateMachine``
document's own ``m_DefaultState`` as independently reachable (rather than
first proving that nested state machine itself is reachable from its
parent), because the exact wire representation of "how a nested state
machine is entered" was not present in the one real sample this project
verified the format against -- see ``connectors.unity_controller_scan``'s
docstring. For a flat (non-nested) state machine, which covers the common
case, this is a precise, complete reachability check.

Both this module and Animation Bug Detection share a single parsing pass
over each ``.controller`` file (``scan_controllers``) rather than walking
the project twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from spiced.connectors.unity_controller_scan import scan_controllers
from spiced.storage.animation_state_machine_reports import (
    AnimationStateMachineReport,
    AnimationStateMachineReportRepository,
)
from spiced.storage.projects import Project

SANITY_CHECK_CAVEAT = (
    "Static structural analysis only. 'Unreachable' means no transition or default-state entry "
    "into it was found anywhere in the saved Animator Controller -- it does NOT account for a "
    "script calling Animator.Play(...)/CrossFade(...) by state name directly, which Spiced "
    "cannot see from the file alone; such a state would show here as unreachable even though "
    "your game does actually use it. 'Missing target' findings are more reliable: they mean the "
    "file itself references a fileID that isn't present, which is unusual outside of manual "
    "edits or merge conflicts."
)


class NoUnityFolderError(RuntimeError):
    """Raised when the project has no connected folder to scan."""


@dataclass(frozen=True)
class UnreachableStateFinding:
    controller_file: str
    state_name: str | None
    state_file_id: str


@dataclass(frozen=True)
class MissingTargetFinding:
    controller_file: str
    transition_file_id: str
    missing_kind: str  # "state" | "state machine"
    missing_file_id: str


@dataclass(frozen=True)
class StateMachineScanResult:
    unreachable_states: list[UnreachableStateFinding] = field(default_factory=list)
    missing_targets: list[MissingTargetFinding] = field(default_factory=list)
    controllers_scanned: int = 0
    caveat: str = SANITY_CHECK_CAVEAT

    @property
    def flagged_count(self) -> int:
        return len(self.unreachable_states) + len(self.missing_targets)

    def as_summary_dict(self) -> dict:
        return {
            "controllers_scanned": self.controllers_scanned,
            "unreachable_states": [
                {"controller_file": f.controller_file, "state_name": f.state_name,
                 "state_file_id": f.state_file_id}
                for f in self.unreachable_states
            ],
            "missing_targets": [
                {
                    "controller_file": f.controller_file,
                    "transition_file_id": f.transition_file_id,
                    "missing_kind": f.missing_kind,
                    "missing_file_id": f.missing_file_id,
                }
                for f in self.missing_targets
            ],
        }


def scan_state_machines(project_path: str | Path) -> StateMachineScanResult:
    """Read-only scan of every ``.controller`` file under the project's
    ``Assets/`` folder. Returns an empty-findings result (never raises) if
    the project has no ``Assets/`` folder or no ``.controller`` files."""
    unreachable: list[UnreachableStateFinding] = []
    missing: list[MissingTargetFinding] = []
    controllers = scan_controllers(project_path)

    for controller in controllers:
        reachable: set[str] = set()
        for sm in controller.state_machines.values():
            if sm.default_state_id and sm.default_state_id != "0":
                reachable.add(sm.default_state_id)

        for transition in controller.transitions.values():
            dst_state = transition.dst_state_id
            if dst_state and dst_state != "0":
                if dst_state in controller.states:
                    reachable.add(dst_state)
                else:
                    missing.append(
                        MissingTargetFinding(
                            controller.path, transition.file_id, "state", dst_state
                        )
                    )
            dst_sm = transition.dst_state_machine_id
            if dst_sm and dst_sm != "0" and dst_sm not in controller.state_machines:
                missing.append(
                    MissingTargetFinding(
                        controller.path, transition.file_id, "state machine", dst_sm
                    )
                )

        for state in controller.states.values():
            if state.file_id not in reachable:
                unreachable.append(
                    UnreachableStateFinding(controller.path, state.name, state.file_id)
                )

    return StateMachineScanResult(
        unreachable_states=unreachable,
        missing_targets=missing,
        controllers_scanned=len(controllers),
    )


class AnimationStateMachineCheckService:
    def __init__(self, reports: AnimationStateMachineReportRepository) -> None:
        self._reports = reports

    def scan(self, project: Project) -> tuple[StateMachineScanResult, AnimationStateMachineReport]:
        if not project.path:
            raise NoUnityFolderError(
                "Connect a Unity folder for this project first (Projects screen)."
            )
        result = scan_state_machines(project.path)
        report = self._reports.create(project.id, result.as_summary_dict())
        return result, report

    def history(self, project_id: int, limit: int = 20) -> list[AnimationStateMachineReport]:
        return self._reports.list_for_project(project_id, limit=limit)
