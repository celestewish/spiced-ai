"""Mocap Cleanup Assist (Implementation Bible, Feature 12).

Detection-only (no auto-fix, per the Bible's own scope decision): scans a
raw BVH mocap file -- before it's even imported into the engine, so no
live Unity connection is needed at all, unlike Feature 11 -- for two kinds
of issues an animator would otherwise have to eyeball frame by frame:

1. **Foot sliding** -- the exact same
   ``automation.motion_quality.detect_foot_sliding`` helper Feature 11
   built, reused here rather than re-derived, run against world-space
   joint positions computed via forward kinematics
   (``automation.bvh_mocap.compute_world_positions``) instead of a live
   Unity capture.
2. **Single-frame jitter** -- a joint's rotation spikes away from and
   immediately snaps back to its neighbors' interpolated trend, a common
   raw-mocap noise artifact (marker occlusion, a bad solve frame, ...),
   via ``automation.motion_quality.detect_single_frame_jitter`` against
   each joint's own local rotation curve
   (``automation.bvh_mocap.local_rotation_samples``).

BVH files carry no fixed real-world unit (a "Hips" offset of 1.0 could
mean 1 meter, 1 centimeter, or 1 inch depending on the exporting tool) --
``contact_height``/``slide_speed_threshold`` default to values reasonable
for meter-scale rigs and are exposed as parameters precisely because they
need retuning for a differently-scaled file; this module has no way to
detect a file's unit convention on its own.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from spiced.automation.bvh_mocap import (
    BvhParseError,
    BvhSkeleton,
    compute_world_positions,
    local_rotation_samples,
    parse_bvh,
)
from spiced.automation.finding import Finding, FindingItem
from spiced.automation.motion_quality import detect_foot_sliding, detect_single_frame_jitter
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project

FEATURE_ID = "animation.mocap_cleanup_assist"

DEFAULT_CONTACT_HEIGHT = 0.08
DEFAULT_SLIDE_SPEED_THRESHOLD = 0.35
DEFAULT_JITTER_THRESHOLD_DEG = 15.0

CAVEAT = (
    "Detection only -- Spiced never modifies the mocap file. Foot-sliding and jitter thresholds "
    "are tuned for meter-scale rigs by default; BVH carries no fixed real-world unit, so retune "
    "them for a differently-scaled file (centimeters, inches, ...). Foot joints are auto-guessed "
    "by name (containing 'foot' or 'toe') unless a list is given explicitly -- a non-matching "
    "naming convention means no foot-sliding check runs at all."
)


@dataclass(frozen=True)
class MocapCleanupAnalysis:
    foot_sliding_events: list = field(default_factory=list)
    jitter_frames: list = field(default_factory=list)


def guess_foot_joint_names(skeleton: BvhSkeleton) -> list[str]:
    return [
        name for name in skeleton.joint_names
        if "foot" in name.lower() or "toe" in name.lower()
    ]


def analyze_bvh_mocap(
    skeleton: BvhSkeleton,
    *,
    foot_joint_names: list[str] | None = None,
    contact_height: float = DEFAULT_CONTACT_HEIGHT,
    slide_speed_threshold: float = DEFAULT_SLIDE_SPEED_THRESHOLD,
    jitter_threshold_deg: float = DEFAULT_JITTER_THRESHOLD_DEG,
) -> MocapCleanupAnalysis:
    if foot_joint_names is None:
        foot_joint_names = guess_foot_joint_names(skeleton)

    positions = compute_world_positions(skeleton)
    foot_sliding = []
    for name in foot_joint_names:
        samples = positions.get(name, [])
        foot_sliding.extend(
            detect_foot_sliding(
                name, samples, contact_height=contact_height,
                slide_speed_threshold=slide_speed_threshold,
            )
        )

    jitter = []
    for name, samples in local_rotation_samples(skeleton).items():
        jitter.extend(
            detect_single_frame_jitter(name, samples, jitter_threshold_deg=jitter_threshold_deg)
        )

    return MocapCleanupAnalysis(foot_sliding_events=foot_sliding, jitter_frames=jitter)


def build_finding(analysis: MocapCleanupAnalysis, project_id: str, source_path: str) -> Finding:
    items: list[FindingItem] = []
    for e in analysis.foot_sliding_events:
        items.append(
            FindingItem(
                asset_path=source_path,
                severity="warning",
                message=(
                    f'"{e.joint}" slides {e.peak_speed:.2f} units/sec while grounded, from '
                    f"{e.start_time_s:.2f}s to {e.end_time_s:.2f}s (frames {e.start_frame}-"
                    f"{e.end_frame})."
                ),
                detail={
                    "issue_type": "foot_sliding",
                    "joint": e.joint,
                    "start_frame": e.start_frame,
                    "end_frame": e.end_frame,
                    "start_time_s": e.start_time_s,
                    "end_time_s": e.end_time_s,
                    "peak_speed": e.peak_speed,
                },
            )
        )
    for e in analysis.jitter_frames:
        items.append(
            FindingItem(
                asset_path=source_path,
                severity="warning",
                message=(
                    f'"{e.joint}" jitters {e.deviation_deg:.1f} degrees off-trend at frame '
                    f"{e.frame} ({e.time_s:.2f}s)."
                ),
                detail={
                    "issue_type": "jitter_frame",
                    "joint": e.joint,
                    "frame": e.frame,
                    "time_s": e.time_s,
                    "deviation_deg": e.deviation_deg,
                },
            )
        )

    status = Finding.status_for(items)
    summary = _summarize(analysis)
    return Finding(
        feature_id=FEATURE_ID, project_id=str(project_id), status=status, summary=summary,
        items=items,
    )


def _summarize(analysis: MocapCleanupAnalysis) -> str:
    total = len(analysis.foot_sliding_events) + len(analysis.jitter_frames)
    if total == 0:
        return "Clean take: no foot sliding or jitter found."
    parts = []
    if analysis.foot_sliding_events:
        parts.append(f"{len(analysis.foot_sliding_events)} foot-sliding event(s)")
    if analysis.jitter_frames:
        parts.append(f"{len(analysis.jitter_frames)} jitter frame(s)")
    return "Found " + ", ".join(parts) + "."


def run_mocap_cleanup_assist(
    bvh_path: str | Path,
    project_id: str,
    *,
    foot_joint_names: list[str] | None = None,
    contact_height: float = DEFAULT_CONTACT_HEIGHT,
    slide_speed_threshold: float = DEFAULT_SLIDE_SPEED_THRESHOLD,
    jitter_threshold_deg: float = DEFAULT_JITTER_THRESHOLD_DEG,
) -> Finding:
    try:
        text = Path(bvh_path).read_text(encoding="utf-8", errors="replace")
        skeleton = parse_bvh(text)
    except (OSError, BvhParseError) as exc:
        message = f"Could not read {Path(bvh_path).name} as BVH: {exc}"
        return Finding(
            feature_id=FEATURE_ID, project_id=str(project_id), status="error", summary=message,
            items=[FindingItem(asset_path=str(bvh_path), severity="error", message=message)],
        )

    analysis = analyze_bvh_mocap(
        skeleton, foot_joint_names=foot_joint_names, contact_height=contact_height,
        slide_speed_threshold=slide_speed_threshold, jitter_threshold_deg=jitter_threshold_deg,
    )
    return build_finding(analysis, project_id, str(bvh_path))


class MocapCleanupAssistService:
    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def scan(
        self,
        project: Project,
        bvh_path: str | Path,
        *,
        foot_joint_names: list[str] | None = None,
    ) -> tuple[Finding, AutomationFindingRecord]:
        finding = run_mocap_cleanup_assist(
            bvh_path, str(project.id), foot_joint_names=foot_joint_names
        )
        record = self._findings.create(project.id, finding)
        return finding, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-mocap-cleanup-assist",
        description="Scan a raw BVH mocap take for foot sliding and single-frame jitter.",
    )
    parser.add_argument("bvh_path", help="Path to a .bvh mocap file.")
    parser.add_argument(
        "--foot-joints", nargs="+", default=None,
        help="Foot joint names to check for sliding (default: auto-guessed by name).",
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    finding = run_mocap_cleanup_assist(
        args.bvh_path, args.project_id, foot_joint_names=args.foot_joints
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
