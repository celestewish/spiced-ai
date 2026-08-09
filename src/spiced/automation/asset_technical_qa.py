"""Asset Technical QA Scan (Implementation Bible, Feature 3).

Flags technical issues in art assets before they reach a programmer:
resolution/power-of-two, file-size sanity, source-only format, and mipmap
settings all reuse ``core.asset_review_queue.review_asset`` (Pillow +
verified ``.meta`` YAML introspection -- already built and tested; see that
module's docstring for the "verified against a real Unity ``.meta`` file"
discipline this reuses rather than re-deriving). Naming-convention checking
is pure Python (a per-project regex against each filename). Pivot-point
checking is the one thing that genuinely needs live engine data -- a mesh's
pivot offset relative to its own bounds isn't reliably readable from a raw
file -- so it goes through ``connectors.unity_asset_export``, the same
"launch Unity headlessly, always read the result file" mechanism
``visual_regression_capture`` (Feature 2) established.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from spiced.automation.finding import Finding, FindingItem
from spiced.connectors.unity_asset_export import AssetExportRunResult, run_export
from spiced.core.asset_review_queue import (
    AssetReviewFinding,
    UnreadableAssetError,
    iter_folder_files,
    review_asset,
)
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project

FEATURE_ID = "art.asset_technical_qa"

# A conservative, permissive-by-default convention (letters/digits/
# underscore, must start with a letter) -- projects override via
# Project.asset_naming_pattern (see storage.projects) rather than this
# module hardcoding house style.
DEFAULT_NAMING_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"

# Fraction of a mesh's own bounds size its pivot may sit away from the
# bounds center before being flagged -- a pivot dead-center in the mesh's
# bounds has ratio 0; a pivot sitting at one edge of a roughly cube-shaped
# mesh has ratio ~0.5. 0.1 flags a noticeably off-center pivot without
# flagging every mesh whose pivot isn't mathematically perfect.
DEFAULT_PIVOT_TOLERANCE = 0.1

DEFAULT_EXPORT_TIMEOUT_S = 600

# Unity-importable mesh source formats -- the only files the pivot check
# (which needs a real mesh, not just an image) applies to.
MESH_EXTENSIONS = {".fbx", ".obj", ".blend"}


def to_unity_asset_path(path: str | Path, project_root: str | Path) -> str | None:
    """Convert an absolute filesystem path to a Unity-relative asset path
    (forward slashes, rooted at the project folder), or None if it isn't
    under ``project_root``."""
    try:
        rel = Path(path).resolve().relative_to(Path(project_root).resolve())
    except ValueError:
        return None
    return str(rel).replace("\\", "/")


def check_naming(path: Path, pattern: str = DEFAULT_NAMING_PATTERN) -> FindingItem | None:
    if re.match(pattern, path.stem):
        return None
    return FindingItem(
        asset_path=str(path),
        severity="warning",
        message=f'{path.name}: filename "{path.stem}" doesn\'t match the naming convention.',
        detail={"issue_type": "naming", "expected": pattern, "actual": path.stem},
    )


def _review_finding_to_items(review: AssetReviewFinding) -> list[FindingItem]:
    name = Path(review.path).name
    items: list[FindingItem] = []
    if review.is_power_of_two is False:
        items.append(
            FindingItem(
                asset_path=review.path,
                severity="warning",
                message=f"{name}: {review.width}x{review.height} is not power-of-two.",
                detail={
                    "issue_type": "resolution_po2",
                    "expected": "power-of-two",
                    "actual": f"{review.width}x{review.height}",
                },
            )
        )
    if review.oversized:
        items.append(
            FindingItem(
                asset_path=review.path,
                severity="warning",
                message=(
                    f"{name}: {review.file_size_bytes / (1024 * 1024):.1f} MB is large for an "
                    "uncompressed-prone format."
                ),
                detail={"issue_type": "file_size", "actual": review.file_size_bytes},
            )
        )
    if review.format_warning:
        items.append(
            FindingItem(
                asset_path=review.path,
                severity="warning",
                message=f"{name}: {review.format_warning}",
                detail={"issue_type": "source_only_format"},
            )
        )
    if review.meta_present is False:
        items.append(
            FindingItem(
                asset_path=review.path,
                severity="warning",
                message=f"{name}: no .meta file found -- likely never imported through Unity.",
                detail={"issue_type": "missing_meta"},
            )
        )
    if review.meta_present and review.meta_has_guid is False:
        items.append(
            FindingItem(
                asset_path=review.path,
                severity="warning",
                message=f"{name}: .meta file exists but no guid was found in it.",
                detail={"issue_type": "meta_missing_guid"},
            )
        )
    if review.mipmaps_enabled is False:
        items.append(
            FindingItem(
                asset_path=review.path,
                severity="warning",
                message=f"{name}: mipmaps are disabled.",
                detail={
                    "issue_type": "mipmaps_disabled",
                    "expected": "enabled",
                    "actual": "disabled",
                },
            )
        )
    return items


def scan_local(
    paths: list[Path],
    project_root: str | Path | None,
    naming_pattern: str = DEFAULT_NAMING_PATTERN,
) -> list[FindingItem]:
    """Run every check that needs no live engine connection: resolution/
    PO2/file-size/format/mipmap (via ``core.asset_review_queue``) plus
    naming convention."""
    items: list[FindingItem] = []
    for p in paths:
        try:
            review = review_asset(p, project_root=project_root)
        except UnreadableAssetError as exc:
            items.append(FindingItem(asset_path=str(p), severity="error", message=str(exc)))
            continue
        found = _review_finding_to_items(review)
        naming_item = check_naming(p, naming_pattern)
        if naming_item is not None:
            found.append(naming_item)
        if found:
            items.extend(found)
        else:
            items.append(
                FindingItem(
                    asset_path=str(p),
                    severity="info",
                    message=f"{p.name}: no technical issues found.",
                )
            )
    return items


def scan_pivots(
    unity_path: str,
    project_path: str | Path,
    mesh_paths: list[Path],
    *,
    tolerance: float = DEFAULT_PIVOT_TOLERANCE,
    timeout_s: int = DEFAULT_EXPORT_TIMEOUT_S,
) -> list[FindingItem]:
    """Flag meshes whose pivot sits noticeably off-center in their own
    bounds -- the one check that needs a live Unity Editor (see module
    docstring). Meshes not under ``project_path`` are skipped silently."""
    asset_path_by_rel: dict[str, Path] = {}
    for p in mesh_paths:
        rel = to_unity_asset_path(p, project_path)
        if rel is not None:
            asset_path_by_rel[rel] = p
    if not asset_path_by_rel:
        return []

    result: AssetExportRunResult = run_export(
        unity_path, str(project_path), list(asset_path_by_rel), timeout_s=timeout_s
    )
    if result.error is not None:
        return [
            FindingItem(
                asset_path=str(p), severity="error", message=f"Pivot check failed: {result.error}"
            )
            for p in asset_path_by_rel.values()
        ]

    items: list[FindingItem] = []
    for outcome in result.outcomes:
        p = asset_path_by_rel.get(outcome.asset_path)
        name = p.name if p is not None else outcome.asset_path
        if not outcome.succeeded:
            items.append(
                FindingItem(
                    asset_path=outcome.asset_path,
                    severity="error",
                    message=f"{name}: pivot check failed -- {outcome.error}",
                )
            )
            continue
        if not outcome.bounds_size:  # None or 0 -- degenerate/empty mesh, nothing to say
            continue
        ratio = outcome.pivot_offset / outcome.bounds_size
        if ratio > tolerance:
            items.append(
                FindingItem(
                    asset_path=outcome.asset_path,
                    severity="warning",
                    message=(
                        f"{name}: pivot is off-center by {ratio * 100:.1f}% of the mesh's bounds "
                        "size."
                    ),
                    detail={
                        "issue_type": "pivot_offset",
                        "expected": f"<= {tolerance * 100:.0f}%",
                        "actual": f"{ratio * 100:.1f}%",
                    },
                )
            )
    return items


def _summarize(items: list[FindingItem], asset_count: int) -> str:
    if asset_count == 0:
        return "No assets found to scan."
    # Count distinct flagged *assets*, not raw items -- one asset can carry
    # several issues (e.g. both non-PO2 and bad naming), and "N flagged"
    # should mean N assets worth a look, not N individual issues.
    error_assets = {i.asset_path for i in items if i.severity == "error"}
    flagged_assets = {i.asset_path for i in items if i.severity == "warning"} - error_assets
    if error_assets:
        return (
            f"Scanned {asset_count} asset(s); {len(error_assets)} failed, "
            f"{len(flagged_assets)} flagged for a look."
        )
    if flagged_assets:
        return f"Scanned {asset_count} asset(s); {len(flagged_assets)} flagged for a look."
    return f"Scanned {asset_count} asset(s); no technical issues found."


def run_asset_technical_qa(
    folder_path: str | Path,
    project_id: str,
    *,
    project_root: str | Path | None = None,
    unity_path: str | None = None,
    naming_pattern: str = DEFAULT_NAMING_PATTERN,
    pivot_tolerance: float = DEFAULT_PIVOT_TOLERANCE,
    timeout_s: int = DEFAULT_EXPORT_TIMEOUT_S,
) -> Finding:
    """Scan every asset under ``folder_path``. Pivot checking only runs when
    both ``unity_path`` and ``project_root`` are given -- every other check
    works with neither (see module docstring)."""
    paths = iter_folder_files(folder_path)
    items = scan_local(paths, project_root, naming_pattern)

    if unity_path and project_root:
        mesh_paths = [p for p in paths if p.suffix.lower() in MESH_EXTENSIONS]
        if mesh_paths:
            items.extend(
                scan_pivots(
                    unity_path,
                    project_root,
                    mesh_paths,
                    tolerance=pivot_tolerance,
                    timeout_s=timeout_s,
                )
            )

    status = Finding.status_for(items)
    summary = _summarize(items, len(paths))
    return Finding(
        feature_id=FEATURE_ID,
        project_id=str(project_id),
        status=status,
        summary=summary,
        items=items,
    )


class AssetTechnicalQaService:
    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def scan(
        self, project: Project, folder_path: str | Path, *, unity_path: str | None = None
    ) -> tuple[Finding, AutomationFindingRecord]:
        naming_pattern = project.asset_naming_pattern or DEFAULT_NAMING_PATTERN
        pivot_tolerance = (
            project.asset_pivot_tolerance
            if project.asset_pivot_tolerance is not None
            else DEFAULT_PIVOT_TOLERANCE
        )
        finding = run_asset_technical_qa(
            folder_path,
            str(project.id),
            project_root=project.path,
            unity_path=unity_path,
            naming_pattern=naming_pattern,
            pivot_tolerance=pivot_tolerance,
        )
        record = self._findings.create(project.id, finding)
        return finding, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-asset-technical-qa",
        description=(
            "Scan a folder of art assets for technical issues: resolution/power-of-two, file "
            "size, source-only formats, mipmap settings, naming convention, and (with --unity-path "
            "and --project-path) mesh pivot offset."
        ),
    )
    parser.add_argument("folder", help="Folder of assets to scan (scanned recursively).")
    parser.add_argument(
        "--project-path", default=None, help="Unity project root (enables .meta + pivot checks)."
    )
    parser.add_argument(
        "--unity-path",
        default=None,
        help="Path to the Unity Editor executable (enables pivot checks).",
    )
    parser.add_argument(
        "--naming-pattern",
        default=DEFAULT_NAMING_PATTERN,
        help=f"Regex filenames (without extension) must match (default: {DEFAULT_NAMING_PATTERN}).",
    )
    parser.add_argument(
        "--pivot-tolerance",
        type=float,
        default=DEFAULT_PIVOT_TOLERANCE,
        help=(
            "Max fraction of bounds size a pivot may be off-center "
            f"(default: {DEFAULT_PIVOT_TOLERANCE})."
        ),
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    finding = run_asset_technical_qa(
        args.folder,
        args.project_id,
        project_root=args.project_path,
        unity_path=args.unity_path,
        naming_pattern=args.naming_pattern,
        pivot_tolerance=args.pivot_tolerance,
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
