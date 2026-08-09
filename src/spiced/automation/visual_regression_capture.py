"""Visual Regression Testing (Implementation Bible, Feature 2).

Screenshots a project's "key scenes" each build via a real engine hook
(``connectors.unity_visual_capture``, see the marker-GameObject convention
documented there and in ``docs/visual_regression_capture_hook.md``) and
flags unintended visual changes against the immediately preceding capture.

The pixel-diff itself reuses ``core.visual_regression`` (Pillow
``ImageChops.difference``, the same changed-pixel-ratio algorithm and
2%-changed default threshold already built and tested for the paste/import
Visual Regression feature) -- diffing two images doesn't care whether they
came from a live engine capture or a folder the developer picked by hand,
so only the *sourcing* of images is new here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from spiced.automation.finding import Finding, FindingItem
from spiced.connectors.unity_visual_capture import (
    CaptureRunResult,
    SceneCaptureRequest,
    run_capture,
)
from spiced.core.visual_regression import CHANGE_RATIO_THRESHOLD, UnreadableImageError, diff_pair
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project
from spiced.storage.visual_regression_captures import (
    VisualRegressionCaptureRepository,
)
from spiced.storage.visual_regression_key_scenes import (
    KeySceneRecord,
    VisualRegressionKeySceneRepository,
)

FEATURE_ID = "vfx.visual_regression"
DEFAULT_CHANGE_RATIO_THRESHOLD = CHANGE_RATIO_THRESHOLD
DEFAULT_CAPTURE_TIMEOUT_S = 600


@dataclass(frozen=True)
class KeyScene:
    scene_path: str
    label: str
    marker_name: str


def _slug(label: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip()).strip("_")
    return slug or "scene"


def capture_key_scenes(
    unity_path: str,
    project_path: str,
    key_scenes: list[KeyScene],
    output_dir: str | Path,
    timeout_s: int = DEFAULT_CAPTURE_TIMEOUT_S,
) -> CaptureRunResult:
    """Capture every key scene into ``output_dir``, one PNG per scene
    (named after the scene's label, so re-runs land on stable filenames)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    requests = [
        SceneCaptureRequest(
            scene_path=scene.scene_path,
            marker_name=scene.marker_name,
            output_path=str(output_dir / f"{_slug(scene.label)}.png"),
        )
        for scene in key_scenes
    ]
    return run_capture(unity_path, project_path, requests, timeout_s=timeout_s)


def compare_captures(
    key_scenes: list[KeyScene],
    capture_result: CaptureRunResult,
    previous_dir: str | Path | None,
    project_id: str,
    *,
    threshold: float = DEFAULT_CHANGE_RATIO_THRESHOLD,
    diff_output_dir: str | Path | None = None,
) -> Finding:
    """Build the Finding: diff each successfully-captured scene against its
    same-named file in ``previous_dir`` (the previous capture run, if any)."""
    if capture_result.error is not None:
        return Finding(
            feature_id=FEATURE_ID,
            project_id=str(project_id),
            status="error",
            summary=f"Capture failed: {capture_result.error}",
        )

    outcomes_by_scene = {o.scene_path: o for o in capture_result.outcomes}
    items: list[FindingItem] = []
    for scene in key_scenes:
        outcome = outcomes_by_scene.get(scene.scene_path)
        if outcome is None:
            items.append(
                FindingItem(
                    asset_path=scene.scene_path,
                    severity="error",
                    message=f"{scene.label}: no capture result was returned for this scene.",
                )
            )
            continue
        if not outcome.succeeded:
            items.append(
                FindingItem(
                    asset_path=scene.scene_path,
                    severity="error",
                    message=f"{scene.label}: capture failed -- {outcome.error}",
                )
            )
            continue

        current_path = Path(outcome.output_path)
        previous_path = Path(previous_dir) / current_path.name if previous_dir else None
        if previous_path is None or not previous_path.is_file():
            items.append(
                FindingItem(
                    asset_path=scene.scene_path,
                    severity="info",
                    message=f"{scene.label}: captured (no previous build to compare against).",
                    detail={"after_image": str(current_path)},
                )
            )
            continue

        save_diff_to = (
            Path(diff_output_dir) / f"diff_{current_path.name}" if diff_output_dir else None
        )
        try:
            diff = diff_pair(previous_path, current_path, save_diff_to=save_diff_to)
        except UnreadableImageError as exc:
            items.append(
                FindingItem(
                    asset_path=scene.scene_path,
                    severity="error",
                    message=f"{scene.label}: couldn't diff against the previous capture -- {exc}",
                )
            )
            continue

        changed = diff.changed_pixel_ratio >= threshold
        percent = round(diff.changed_pixel_ratio * 100, 2)
        items.append(
            FindingItem(
                asset_path=scene.scene_path,
                severity="warning" if changed else "info",
                message=(
                    f"{scene.label}: {percent:.1f}% pixels changed"
                    + (" (flagged)" if changed else "")
                ),
                detail={
                    "before_image": str(previous_path),
                    "after_image": str(current_path),
                    "diff_image": diff.diff_image_path,
                    "percent_changed": percent,
                },
            )
        )

    status = Finding.status_for(items)
    summary = _summarize(items, len(key_scenes))
    return Finding(
        feature_id=FEATURE_ID,
        project_id=str(project_id),
        status=status,
        summary=summary,
        items=items,
    )


def _summarize(items: list[FindingItem], scene_count: int) -> str:
    if scene_count == 0:
        return "No key scenes configured to capture."
    errors = sum(1 for i in items if i.severity == "error")
    flagged = sum(1 for i in items if i.severity == "warning")
    if errors:
        return (
            f"Captured {scene_count} key scene(s); {errors} failed, {flagged} flagged as changed."
        )
    if flagged:
        return (
            f"Captured {scene_count} key scene(s); {flagged} flagged as changed "
            "vs. the previous build."
        )
    return f"Captured {scene_count} key scene(s); no unexpected changes vs. the previous build."


def run_visual_regression(
    unity_path: str,
    project_path: str,
    key_scenes: list[KeyScene],
    output_dir: str | Path,
    project_id: str,
    *,
    previous_dir: str | Path | None = None,
    threshold: float = DEFAULT_CHANGE_RATIO_THRESHOLD,
    timeout_s: int = DEFAULT_CAPTURE_TIMEOUT_S,
) -> tuple[Finding, CaptureRunResult]:
    """Capture every key scene, then diff against ``previous_dir`` (if given)."""
    capture_result = capture_key_scenes(
        unity_path, project_path, key_scenes, output_dir, timeout_s=timeout_s
    )
    diff_dir = Path(output_dir) / "diffs"
    finding = compare_captures(
        key_scenes,
        capture_result,
        previous_dir,
        project_id,
        threshold=threshold,
        diff_output_dir=diff_dir,
    )
    return finding, capture_result


class NoKeyScenesError(RuntimeError):
    """Raised when a project has no key scenes configured to capture."""


class UnityUnavailableError(RuntimeError):
    """Raised when no matching Unity Editor install can be resolved."""


class VisualRegressionCaptureService:
    """Wires ``run_visual_regression`` to a real project: key-scene config,
    capture-run history (for "previous build" lookup), and a persisted
    Finding -- for GUI/chatbox callers."""

    def __init__(
        self,
        key_scenes: VisualRegressionKeySceneRepository,
        captures: VisualRegressionCaptureRepository,
        findings: AutomationFindingRepository,
    ) -> None:
        self._key_scenes = key_scenes
        self._captures = captures
        self._findings = findings

    # --- Key scene config --------------------------------------------------

    def add_key_scene(
        self, project_id: int, scene_path: str, label: str, marker_name: str
    ) -> KeySceneRecord:
        return self._key_scenes.add(project_id, scene_path, label, marker_name)

    def list_key_scenes(self, project_id: int) -> list[KeySceneRecord]:
        return self._key_scenes.list_for_project(project_id)

    def remove_key_scene(self, key_scene_id: int) -> None:
        self._key_scenes.delete(key_scene_id)

    # --- Capture + compare ---------------------------------------------------

    def run(
        self, project: Project, unity_path: str, *, timeout_s: int = DEFAULT_CAPTURE_TIMEOUT_S
    ) -> tuple[Finding, AutomationFindingRecord]:
        if not project.path:
            raise UnityUnavailableError("Connect a Unity folder for this project first.")
        scenes = [
            KeyScene(scene_path=r.scene_path, label=r.label, marker_name=r.marker_name)
            for r in self._key_scenes.list_for_project(project.id)
        ]
        if not scenes:
            raise NoKeyScenesError(
                f'No key scenes are configured for "{project.name}". Add at least one scene/'
                "marker pair first."
            )

        previous = self._captures.latest_for_project(project.id)
        output_dir = _captures_dir(project.path) / _timestamp_slug()

        finding, _capture_result = run_visual_regression(
            unity_path,
            project.path,
            scenes,
            output_dir,
            str(project.id),
            previous_dir=previous.screenshots_dir if previous else None,
            timeout_s=timeout_s,
        )
        self._captures.create(project.id, str(output_dir))
        record = self._findings.create(project.id, finding)
        return finding, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _captures_dir(project_path: str) -> Path:
    return Path(project_path) / "SpicedVisualRegression"


def _timestamp_slug() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-visual-regression-capture",
        description=(
            "Capture a Unity project's key scenes and flag unexpected visual changes vs. a "
            "previous capture. Standalone -- doesn't need a Spiced project database."
        ),
    )
    parser.add_argument("unity_path", help="Path to the Unity Editor executable.")
    parser.add_argument("project_path", help="Path to the Unity project folder.")
    parser.add_argument(
        "--scenes-config",
        required=True,
        help=(
            "JSON file: a list of {\"scene_path\": ..., \"label\": ..., \"marker_name\": ...} "
            "objects, one per key scene."
        ),
    )
    parser.add_argument("--output-dir", required=True, help="Where to write this run's captures.")
    parser.add_argument(
        "--previous-dir",
        default=None,
        help="A previous run's output directory to diff against (omit to skip comparison).",
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_CHANGE_RATIO_THRESHOLD,
        help=f"Changed-pixel-ratio flag threshold (default: {DEFAULT_CHANGE_RATIO_THRESHOLD}).",
    )
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    try:
        raw_scenes = json.loads(Path(args.scenes_config).read_text(encoding="utf-8"))
        scenes = [
            KeyScene(
                scene_path=s["scene_path"], label=s["label"], marker_name=s["marker_name"]
            )
            for s in raw_scenes
        ]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"Couldn't read --scenes-config: {exc}", file=sys.stderr)
        return 1

    finding, _capture_result = run_visual_regression(
        args.unity_path,
        args.project_path,
        scenes,
        args.output_dir,
        args.project_id,
        previous_dir=args.previous_dir,
        threshold=args.threshold,
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
