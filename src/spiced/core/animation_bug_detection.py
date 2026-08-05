"""Animation Bug Detection (Phase I, section 8, Core tier).

True runtime animation-bug detection -- T-posing, foot-sliding, a visibly
snapping transition -- requires observing the game actually running, which
is genuinely infeasible for a static, read-only scan; Spiced never executes
or renders a scene (see README's local-first principle and the narrow,
already-established exceptions like Run Unity Tests/Build Pipeline, neither
of which renders anything). This module instead parses Animator Controller
(``.controller``) files (``connectors.unity_controller_scan``, whose
docstring documents exactly what was verified against a real Unity-generated
sample vs. inferred) for two structural **risk indicators**:

1. **States with no motion assigned** (``m_Motion: {fileID: 0}``) -- a real,
   common cause of visible T-posing, since an empty state shows the
   Animator's default/bind pose. A false positive here is possible for a
   deliberately empty placeholder state that's never actually reached at
   runtime (see State Machine Sanity Check for reachability, a separate,
   complementary scan).
2. **Zero-duration transitions** (``m_TransitionDuration: 0``) -- can cause a
   visible instant "snap" rather than a blend between two states. Unity's
   ``.controller`` schema gives no static way to know whether the two states
   involved are visually distinct (that needs comparing the actual animation
   clips' content, out of scope here) or whether a zero duration is
   deliberate (e.g. two states that are meant to look identical, or an
   immediate-cut design choice) -- so every zero-duration, non-exit
   transition is flagged, which will include legitimate ones as false
   positives.

Every finding is a **risk indicator inferred from static structure**, never
a claim of a confirmed runtime bug -- this distinction is repeated in every
result's caveat text and in the Animation screen's copy, per the same
honesty discipline as Dead Reference Detection / Naming Consistency.

State Machine Sanity Check (``core.animation_state_machine_check``) is the
more rigorously verifiable sibling of this module (unreachable states /
missing transition targets are real static-analysis facts, not inference)
-- both share the same parsing pass over the same ``.controller`` files via
``connectors.unity_controller_scan.scan_controllers``, rather than walking
the project twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from spiced.connectors.unity_controller_scan import ParsedController, scan_controllers

RISK_INDICATOR_CAVEAT = (
    "Risk indicators only, inferred from the Animator Controller's saved structure -- NOT "
    "confirmed runtime bugs. Spiced never runs your game, so it cannot observe an actual "
    "T-pose, foot-sliding, or a visible snap. An empty state can be an intentional placeholder "
    "that's never reached at runtime (see State Machine Sanity Check for reachability); a "
    "zero-duration transition can be a deliberate instant cut. Treat every item here as worth a "
    "look in the Animator window, never as a confirmed defect."
)


@dataclass(frozen=True)
class EmptyStateFinding:
    controller_file: str
    state_name: str | None
    state_file_id: str


@dataclass(frozen=True)
class ZeroDurationTransitionFinding:
    controller_file: str
    transition_file_id: str
    from_state_name: str | None
    to_state_name: str | None


@dataclass(frozen=True)
class AnimationBugScanResult:
    empty_states: list[EmptyStateFinding] = field(default_factory=list)
    zero_duration_transitions: list[ZeroDurationTransitionFinding] = field(default_factory=list)
    controllers_scanned: int = 0
    caveat: str = RISK_INDICATOR_CAVEAT

    @property
    def flagged_count(self) -> int:
        return len(self.empty_states) + len(self.zero_duration_transitions)


def _scan_one(
    controller: ParsedController,
) -> tuple[list[EmptyStateFinding], list[ZeroDurationTransitionFinding]]:
    # Best-effort "which state does this transition leave from" lookup, built
    # from each state's own m_Transitions list plus each state machine's
    # m_AnyStateTransitions -- a transition not referenced by either (e.g. an
    # entry transition into a nested state machine) is reported with an
    # unknown source rather than guessed at.
    source_of_transition: dict[str, str | None] = {}
    for state in controller.states.values():
        for t_id in state.transition_ids:
            source_of_transition.setdefault(t_id, state.name)
    for sm in controller.state_machines.values():
        for t_id in sm.any_state_transition_ids:
            source_of_transition.setdefault(t_id, "Any State")

    empty_states = [
        EmptyStateFinding(controller.path, state.name, state.file_id)
        for state in controller.states.values()
        if not state.has_motion
    ]

    zero_duration = []
    for transition in controller.transitions.values():
        if transition.transition_duration != 0:
            continue
        if transition.is_exit:
            continue  # a transition to "Exit" has no visible destination pose to snap to
        to_name = None
        if transition.dst_state_id and transition.dst_state_id in controller.states:
            to_name = controller.states[transition.dst_state_id].name
        zero_duration.append(
            ZeroDurationTransitionFinding(
                controller_file=controller.path,
                transition_file_id=transition.file_id,
                from_state_name=source_of_transition.get(transition.file_id),
                to_state_name=to_name,
            )
        )
    return empty_states, zero_duration


def detect_animation_bugs(project_path: str | Path) -> AnimationBugScanResult:
    """Read-only scan of every ``.controller`` file under the project's
    ``Assets/`` folder. Returns an empty-findings result (never raises) if
    the project has no ``Assets/`` folder or no ``.controller`` files."""
    empty_states: list[EmptyStateFinding] = []
    zero_duration: list[ZeroDurationTransitionFinding] = []
    controllers = scan_controllers(project_path)
    for controller in controllers:
        es, zd = _scan_one(controller)
        empty_states.extend(es)
        zero_duration.extend(zd)
    return AnimationBugScanResult(
        empty_states=empty_states,
        zero_duration_transitions=zero_duration,
        controllers_scanned=len(controllers),
    )
