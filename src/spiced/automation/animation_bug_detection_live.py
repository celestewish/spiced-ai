"""Automated Animation Bug Detection, Live Capture (Implementation Bible,
Feature 11).

Catches foot-sliding, T-posing, and popping transitions from real runtime
data (a live Unity Play Mode capture via
``connectors.unity_playtest_capture``), not the file-structure inference
``core.animation_bug_detection`` is limited to (see that module's
docstring for exactly why it can't do this, and why this feature is a
deliberate, considered exception to Spiced's local-first/read-only
principle -- approved for this feature specifically). Both modules stay
side by side: this is a live-capture addition, not a replacement.

Three checks, all computed from the same one playtest capture:

1. **Foot sliding** -- reuses ``automation.motion_quality.
   detect_foot_sliding`` (the helper this feature builds and Feature 12,
   Mocap Cleanup Assist, also imports) against each foot bone's captured
   world-position time series.
2. **T-pose frames** -- a frame where a large fraction of tracked bones'
   evaluated rotations are all simultaneously close to their bind-pose
   rotation is the real runtime signature of a T-pose (the same
   "no motion assigned -> shows bind pose" mechanism
   ``core.animation_bug_detection`` documents as a *risk indicator* from
   static structure -- this checks the live evaluated pose directly
   instead of inferring it).
3. **Snap transitions** -- reuses ``automation.motion_quality.
   detect_angular_velocity_spikes`` per tracked bone, keeping only the
   spikes that land on a frame where the Animator's active state name
   just changed from the previous frame (i.e. genuinely at a transition,
   not merely a fast bone movement mid-clip).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from spiced.automation.finding import Finding, FindingItem
from spiced.automation.motion_quality import (
    PositionSample,
    RotationSample,
    detect_angular_velocity_spikes,
    detect_foot_sliding,
)
from spiced.connectors.unity_controller_scan import scan_controllers
from spiced.connectors.unity_playtest_capture import (
    PlaytestCaptureRequest,
    PlaytestCaptureResult,
    run_playtest_capture,
)
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project

FEATURE_ID = "animation.live_playtest_bug_detection"

# A foot at or below this world-space height (in the capture's own units,
# typically meters) is considered "grounded" for sliding purposes.
DEFAULT_CONTACT_HEIGHT = 0.08
# Horizontal speed (units/sec) a grounded foot can move at before it counts
# as sliding rather than ordinary small settling motion/capture noise.
DEFAULT_SLIDE_SPEED_THRESHOLD = 0.35
# Fraction of tracked bones that must simultaneously sit within
# DEFAULT_TPOSE_EPSILON_DEG of their bind-pose rotation for a frame to
# count as a T-pose frame -- a real T-pose is a *whole-body* reversion to
# rest pose, not one bone coincidentally matching it.
DEFAULT_TPOSE_BONE_FRACTION = 0.9
DEFAULT_TPOSE_EPSILON_DEG = 2.0
# Angular velocity (deg/sec) a bone's rotation can change at across one
# frame before it's a real, visible snap rather than a fast blend.
DEFAULT_SNAP_THRESHOLD_DEG_S = 720.0

CAVEAT = (
    "Live Play Mode capture, not static inference -- foot-sliding, T-pose, and snap-transition "
    "flags here are computed from real evaluated bone positions/rotations sampled while Unity "
    "actually played through the requested states. This is Spiced's one deliberate exception to "
    "its local-first/read-only default (see core.animation_bug_detection's docstring); it is only "
    "as good as the states/bones/thresholds it was run with -- a state or bone not included in "
    "this run is simply not checked."
)


@dataclass(frozen=True)
class TposeFrameEvent:
    frame: int
    time_s: float
    state_name: str
    matched_bone_fraction: float


@dataclass(frozen=True)
class SnapTransitionEvent:
    bone: str
    frame: int
    time_s: float
    angular_speed_deg_s: float
    from_state: str
    to_state: str


@dataclass(frozen=True)
class LivePlaytestAnalysis:
    foot_sliding_events: list = field(default_factory=list)
    tpose_frames: list[TposeFrameEvent] = field(default_factory=list)
    snap_transitions: list[SnapTransitionEvent] = field(default_factory=list)


def infer_state_names(project_path: str | Path) -> list[str]:
    """Real Animator state names, reused from Feature 7's already-parsed
    ``.controller`` data (``connectors.unity_controller_scan``), so a
    developer doesn't have to retype every state name by hand."""
    names: list[str] = []
    seen: set[str] = set()
    for controller in scan_controllers(project_path):
        for state in controller.states.values():
            if state.name and state.name not in seen:
                seen.add(state.name)
                names.append(state.name)
    return names


def detect_tpose_frames(
    frames,
    bind_pose_rotations: dict[str, tuple[float, float, float]],
    *,
    bone_fraction: float = DEFAULT_TPOSE_BONE_FRACTION,
    epsilon_deg: float = DEFAULT_TPOSE_EPSILON_DEG,
) -> list[TposeFrameEvent]:
    if not bind_pose_rotations:
        return []
    events: list[TposeFrameEvent] = []
    for i, f in enumerate(frames):
        tracked = [b for b in bind_pose_rotations if b in f.bone_rotations_euler]
        if not tracked:
            continue
        matches = sum(
            1
            for b in tracked
            if _angular_delta(f.bone_rotations_euler[b], bind_pose_rotations[b]) <= epsilon_deg
        )
        fraction = matches / len(tracked)
        if fraction >= bone_fraction:
            events.append(
                TposeFrameEvent(
                    frame=i, time_s=f.time_s, state_name=f.state_name,
                    matched_bone_fraction=round(fraction, 3),
                )
            )
    return events


def _angular_delta(a, b) -> float:
    return sum((a[k] - b[k]) ** 2 for k in range(3)) ** 0.5


def detect_snap_transitions(
    frames,
    *,
    threshold_deg_s: float = DEFAULT_SNAP_THRESHOLD_DEG_S,
) -> list[SnapTransitionEvent]:
    bone_names: set[str] = set()
    for f in frames:
        bone_names.update(f.bone_rotations_euler.keys())

    events: list[SnapTransitionEvent] = []
    for bone in sorted(bone_names):
        samples = [
            RotationSample(i, f.time_s, f.bone_rotations_euler[bone])
            for i, f in enumerate(frames)
            if bone in f.bone_rotations_euler
        ]
        for spike in detect_angular_velocity_spikes(bone, samples, threshold_deg_s=threshold_deg_s):
            i = spike.frame
            if i <= 0 or i >= len(frames):
                continue
            if frames[i].state_name != frames[i - 1].state_name:
                events.append(
                    SnapTransitionEvent(
                        bone=bone,
                        frame=i,
                        time_s=spike.time_s,
                        angular_speed_deg_s=round(spike.angular_speed_deg_s, 2),
                        from_state=frames[i - 1].state_name,
                        to_state=frames[i].state_name,
                    )
                )
    return events


def analyze_playtest_capture(
    result: PlaytestCaptureResult,
    *,
    foot_bone_names: list[str],
    contact_height: float = DEFAULT_CONTACT_HEIGHT,
    slide_speed_threshold: float = DEFAULT_SLIDE_SPEED_THRESHOLD,
    tpose_bone_fraction: float = DEFAULT_TPOSE_BONE_FRACTION,
    tpose_epsilon_deg: float = DEFAULT_TPOSE_EPSILON_DEG,
    snap_threshold_deg_s: float = DEFAULT_SNAP_THRESHOLD_DEG_S,
) -> LivePlaytestAnalysis:
    """Pure analysis over an already-captured ``PlaytestCaptureResult`` --
    no subprocess/Unity call happens here, which is what lets this be
    fully unit tested against synthetic capture data."""
    foot_sliding = []
    for bone in foot_bone_names:
        samples = [
            PositionSample(i, f.time_s, f.foot_positions[bone])
            for i, f in enumerate(result.frames)
            if bone in f.foot_positions
        ]
        foot_sliding.extend(
            detect_foot_sliding(
                bone, samples, contact_height=contact_height,
                slide_speed_threshold=slide_speed_threshold,
            )
        )

    tpose_frames = detect_tpose_frames(
        result.frames, result.bind_pose_rotations,
        bone_fraction=tpose_bone_fraction, epsilon_deg=tpose_epsilon_deg,
    )
    snap_transitions = detect_snap_transitions(result.frames, threshold_deg_s=snap_threshold_deg_s)

    return LivePlaytestAnalysis(
        foot_sliding_events=foot_sliding, tpose_frames=tpose_frames,
        snap_transitions=snap_transitions,
    )


def build_finding(analysis: LivePlaytestAnalysis, project_id: str) -> Finding:
    items: list[FindingItem] = []
    for e in analysis.foot_sliding_events:
        items.append(
            FindingItem(
                asset_path=e.joint,
                severity="warning",
                message=(
                    f'"{e.joint}" slides {e.peak_speed:.2f} units/sec while grounded, from '
                    f"{e.start_time_s:.2f}s to {e.end_time_s:.2f}s."
                ),
                detail={
                    "issue_type": "foot_sliding",
                    "joint": e.joint,
                    "start_time_s": e.start_time_s,
                    "end_time_s": e.end_time_s,
                    "peak_speed": e.peak_speed,
                },
            )
        )
    for e in analysis.tpose_frames:
        items.append(
            FindingItem(
                asset_path=e.state_name,
                severity="warning",
                message=(
                    f'State "{e.state_name}" at {e.time_s:.2f}s shows a T-pose -- '
                    f"{e.matched_bone_fraction * 100:.0f}% of tracked bones match the bind pose."
                ),
                detail={
                    "issue_type": "tpose_frame",
                    "state_name": e.state_name,
                    "time_s": e.time_s,
                    "matched_bone_fraction": e.matched_bone_fraction,
                },
            )
        )
    for e in analysis.snap_transitions:
        items.append(
            FindingItem(
                asset_path=e.bone,
                severity="warning",
                message=(
                    f'"{e.bone}" snaps {e.angular_speed_deg_s:.0f} deg/sec at {e.time_s:.2f}s '
                    f"during the {e.from_state} -> {e.to_state} transition."
                ),
                detail={
                    "issue_type": "snap_transition",
                    "bone": e.bone,
                    "time_s": e.time_s,
                    "angular_speed_deg_s": e.angular_speed_deg_s,
                    "from_state": e.from_state,
                    "to_state": e.to_state,
                },
            )
        )

    status = Finding.status_for(items)
    summary = _summarize(analysis)
    return Finding(
        feature_id=FEATURE_ID, project_id=str(project_id), status=status, summary=summary,
        items=items,
    )


def _summarize(analysis: LivePlaytestAnalysis) -> str:
    total = (
        len(analysis.foot_sliding_events) + len(analysis.tpose_frames)
        + len(analysis.snap_transitions)
    )
    if total == 0:
        return "Clean run: no foot sliding, T-posing, or snap transitions found."
    parts = []
    if analysis.foot_sliding_events:
        parts.append(f"{len(analysis.foot_sliding_events)} foot-sliding event(s)")
    if analysis.tpose_frames:
        parts.append(f"{len(analysis.tpose_frames)} T-pose frame(s)")
    if analysis.snap_transitions:
        parts.append(f"{len(analysis.snap_transitions)} snap transition(s)")
    return "Found " + ", ".join(parts) + "."


def run_live_animation_bug_detection(
    unity_path: str,
    project_path: str | Path,
    project_id: str,
    *,
    scene_path: str,
    marker_name: str,
    foot_bone_names: list[str],
    tracked_bone_names: list[str],
    state_names: list[str] | None = None,
    sample_interval_s: float = 1.0 / 30.0,
    max_state_duration_s: float = 2.0,
    timeout_s: int = 600,
) -> Finding:
    resolved_states = state_names or infer_state_names(project_path)
    if not resolved_states:
        message = (
            "No Animator states to play through -- pass state_names explicitly, or make sure "
            "this project has at least one .controller file Feature 7's scan can read."
        )
        return Finding(
            feature_id=FEATURE_ID, project_id=str(project_id), status="error", summary=message,
            items=[FindingItem(asset_path=str(project_path), severity="error", message=message)],
        )

    request = PlaytestCaptureRequest(
        scene_path=scene_path,
        marker_name=marker_name,
        state_names=resolved_states,
        foot_bone_names=foot_bone_names,
        tracked_bone_names=tracked_bone_names,
        sample_interval_s=sample_interval_s,
        max_state_duration_s=max_state_duration_s,
    )
    result = run_playtest_capture(unity_path, str(project_path), request, timeout_s=timeout_s)
    if result.error is not None:
        return Finding(
            feature_id=FEATURE_ID, project_id=str(project_id), status="error",
            summary=result.error,
            items=[FindingItem(asset_path=scene_path, severity="error", message=result.error)],
        )

    analysis = analyze_playtest_capture(result, foot_bone_names=foot_bone_names)
    return build_finding(analysis, project_id)


class LiveAnimationBugDetectionService:
    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def run(
        self,
        project: Project,
        unity_path: str,
        *,
        scene_path: str,
        marker_name: str,
        foot_bone_names: list[str],
        tracked_bone_names: list[str],
        state_names: list[str] | None = None,
    ) -> tuple[Finding, AutomationFindingRecord]:
        finding = run_live_animation_bug_detection(
            unity_path, project.path, str(project.id), scene_path=scene_path,
            marker_name=marker_name, foot_bone_names=foot_bone_names,
            tracked_bone_names=tracked_bone_names, state_names=state_names,
        )
        record = self._findings.create(project.id, finding)
        return finding, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-live-animation-bug-detection",
        description=(
            "Play through a set of Animator states in a live Unity Play Mode capture and check "
            "for foot sliding, T-posing, and snap transitions from the real evaluated pose data."
        ),
    )
    parser.add_argument("unity_path", help="Unity Editor executable.")
    parser.add_argument("project_path", help="Path to the Unity project folder.")
    parser.add_argument(
        "scene_path", help="Unity-relative scene path to open, e.g. Assets/Main.unity."
    )
    parser.add_argument("marker_name", help="Name of the character root GameObject to drive.")
    parser.add_argument(
        "--foot-bones", nargs="+", required=True, help="Foot bone names to check for sliding."
    )
    parser.add_argument(
        "--tracked-bones", nargs="+", required=True,
        help="Bone names to sample rotations for (T-pose/snap checks).",
    )
    parser.add_argument(
        "--states", nargs="+", default=None,
        help="Animator state names to play through (default: inferred from .controller files).",
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    finding = run_live_animation_bug_detection(
        args.unity_path, args.project_path, args.project_id, scene_path=args.scene_path,
        marker_name=args.marker_name, foot_bone_names=args.foot_bones,
        tracked_bone_names=args.tracked_bones, state_names=args.states,
    )

    if args.json:
        print(json.dumps(finding.as_dict(), indent=2))
    else:
        print(finding.summary)
        for item in finding.items:
            print(f"  [{item.severity}] {item.message}")

    return 1 if finding.status == "error" else 0


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":
    main()
