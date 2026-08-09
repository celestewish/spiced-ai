"""Shader Variant & Compile Bloat Analysis (Implementation Bible, Feature 6).

Flags shaders whose compiled variant count is bloating build size and
compile time. Shader discovery reuses ``connectors.unity_scan.iter_assets``
(the same read-only project walk every recursive scan in this codebase
uses); variant counts come from Unity's own Editor via
``connectors.unity_shader_variant_export`` (see that module's docstring for
why this uses a documented API instead of parsing log text).

"Estimated compile time" is a clearly-labeled proxy (variant_count *
a documented per-variant estimate), not a measured value -- Spiced has no
way to measure real shader compile time, the same "proxy, not a real
number" discipline ``core.shader_performance_profiling`` already applies to
its own line-count-based complexity heuristic.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from spiced.automation.finding import Finding, FindingItem
from spiced.connectors.unity_scan import iter_assets
from spiced.connectors.unity_shader_variant_export import ShaderVariantRunResult, run_export
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project

FEATURE_ID = "vfx.shader_variant_analysis"

# A shader with more variants than this is flagged as a compile-bloat
# candidate -- a documented, conservative starting point (a shader with a
# handful of keyword multi_compile directives easily reaches the hundreds;
# this flags projects worth a second look, not a hard engineering limit).
DEFAULT_VARIANT_THRESHOLD = 100
# Rough, documented per-variant compile-time proxy in milliseconds -- not a
# measurement. Real compile time depends on target platform, graphics API,
# and driver shader compiler, none of which Spiced can see.
DEFAULT_MS_PER_VARIANT = 2.0
DEFAULT_TOP_N = 10
SHADER_EXTENSION = ".shader"


def to_unity_asset_path(path: str | Path, project_root: str | Path) -> str | None:
    """Convert an absolute filesystem path to a Unity-relative asset path."""
    try:
        rel = Path(path).resolve().relative_to(Path(project_root).resolve())
    except ValueError:
        return None
    return str(rel).replace("\\", "/")


def find_shader_paths(project_path: str | Path) -> list[str]:
    """Unity-relative paths of every ``.shader`` file under the project's
    ``Assets/`` folder."""
    root = Path(project_path)
    paths = []
    for p in iter_assets(root):
        if p.suffix.lower() == SHADER_EXTENSION:
            rel = to_unity_asset_path(p, root)
            if rel is not None:
                paths.append(rel)
    return sorted(paths)


@dataclass(frozen=True)
class ShaderVariantStats:
    shader_path: str
    variant_count: int
    pass_count: int
    estimated_compile_time_ms: float
    possibly_unused: bool = False


def build_finding(
    run_result: ShaderVariantRunResult,
    project_id: str,
    *,
    threshold: int = DEFAULT_VARIANT_THRESHOLD,
    ms_per_variant: float = DEFAULT_MS_PER_VARIANT,
    top_n: int = DEFAULT_TOP_N,
    used_shader_names: set[str] | None = None,
) -> Finding:
    if run_result.error is not None:
        return Finding(
            feature_id=FEATURE_ID,
            project_id=str(project_id),
            status="error",
            summary=f"Shader variant export failed: {run_result.error}",
        )

    items: list[FindingItem] = []
    stats: list[ShaderVariantStats] = []
    for outcome in run_result.outcomes:
        name = Path(outcome.shader_path).name
        if not outcome.succeeded:
            items.append(
                FindingItem(
                    asset_path=outcome.shader_path,
                    severity="error",
                    message=f"{name}: variant export failed -- {outcome.error}",
                )
            )
            continue
        variant_count = outcome.variant_count or 0
        pass_count = outcome.pass_count or 0
        estimated_ms = variant_count * ms_per_variant
        possibly_unused = (
            used_shader_names is not None and outcome.shader_path not in used_shader_names
        )
        stats.append(
            ShaderVariantStats(
                shader_path=outcome.shader_path,
                variant_count=variant_count,
                pass_count=pass_count,
                estimated_compile_time_ms=estimated_ms,
                possibly_unused=possibly_unused,
            )
        )

    # Worst offenders first, by variant count -- matches the Bible's "top N
    # worst offenders by variant count" summary framing.
    stats.sort(key=lambda s: s.variant_count, reverse=True)
    for rank, s in enumerate(stats):
        over_threshold = s.variant_count > threshold
        if not over_threshold and not s.possibly_unused:
            severity = "info"
            message = f"{Path(s.shader_path).name}: {s.variant_count} variant(s)."
        else:
            severity = "warning"
            flags = []
            if over_threshold:
                flags.append(f"over the {threshold}-variant threshold")
            if s.possibly_unused:
                flags.append("not seen in the used-shaders list")
            flag_text = ", ".join(flags)
            message = f"{Path(s.shader_path).name}: {s.variant_count} variant(s) ({flag_text})."
        detail = {
            "shader_name": s.shader_path,
            "variant_count": s.variant_count,
            "pass_count": s.pass_count,
            "estimated_compile_time_ms": round(s.estimated_compile_time_ms, 1),
        }
        if rank < top_n and over_threshold:
            detail["top_offender_rank"] = rank + 1
        items.append(
            FindingItem(
                asset_path=s.shader_path, severity=severity, message=message, detail=detail
            )
        )

    status = Finding.status_for(items)
    summary = _summarize(items, len(run_result.outcomes))
    return Finding(
        feature_id=FEATURE_ID,
        project_id=str(project_id),
        status=status,
        summary=summary,
        items=items,
    )


def _summarize(items: list[FindingItem], shader_count: int) -> str:
    if shader_count == 0:
        return "No .shader files found to analyze."
    errors = sum(1 for i in items if i.severity == "error")
    flagged = sum(1 for i in items if i.severity == "warning")
    if errors:
        return (
            f"Analyzed {shader_count} shader(s); {errors} failed, "
            f"{flagged} flagged for variant bloat."
        )
    if flagged:
        return f"Analyzed {shader_count} shader(s); {flagged} flagged for variant bloat."
    return f"Analyzed {shader_count} shader(s); no variant bloat found."


def analyze_shader_variants(
    unity_path: str,
    project_path: str | Path,
    project_id: str,
    *,
    threshold: int = DEFAULT_VARIANT_THRESHOLD,
    ms_per_variant: float = DEFAULT_MS_PER_VARIANT,
    top_n: int = DEFAULT_TOP_N,
    used_shader_names: set[str] | None = None,
    timeout_s: int = 600,
) -> Finding:
    shader_paths = find_shader_paths(project_path)
    if not shader_paths:
        return Finding(
            feature_id=FEATURE_ID,
            project_id=str(project_id),
            status="pass",
            summary="No .shader files found to analyze.",
        )
    run_result = run_export(unity_path, str(project_path), shader_paths, timeout_s=timeout_s)
    return build_finding(
        run_result,
        project_id,
        threshold=threshold,
        ms_per_variant=ms_per_variant,
        top_n=top_n,
        used_shader_names=used_shader_names,
    )


class ShaderVariantAnalysisService:
    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def scan(
        self, project: Project, unity_path: str
    ) -> tuple[Finding, AutomationFindingRecord]:
        threshold = (
            project.shader_variant_threshold
            if project.shader_variant_threshold is not None
            else DEFAULT_VARIANT_THRESHOLD
        )
        finding = analyze_shader_variants(
            unity_path, project.path, str(project.id), threshold=threshold
        )
        record = self._findings.create(project.id, finding)
        return finding, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-shader-variant-analysis",
        description="Check for redundant shader variants bloating the build.",
    )
    parser.add_argument("unity_path", help="Path to the Unity Editor executable.")
    parser.add_argument("project_path", help="Path to the Unity project folder.")
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_VARIANT_THRESHOLD,
        help=f"Variant-count flag threshold (default: {DEFAULT_VARIANT_THRESHOLD}).",
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    finding = analyze_shader_variants(
        args.unity_path, args.project_path, args.project_id, threshold=args.threshold
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
