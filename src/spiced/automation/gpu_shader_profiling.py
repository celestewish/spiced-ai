"""Shader Performance Profiling (Implementation Bible, Feature 9).

Flags shaders too expensive for a target hardware tier, using real captured
GPU frame data -- see ``connectors.renderdoc_analysis`` for how that data
is obtained (RenderDoc's Python API, **not verified against a real
RenderDoc install in this environment** -- read that module's docstring
before relying on the capture-analysis step). Everything in *this* module
(budget computation, ranking, Finding-building) works on the resulting
``ShaderGpuStats`` list regardless of how it was produced, and is fully
tested against synthetic stats.

Named ``gpu_shader_profiling`` (not ``shader_performance_profiling``) to
stay distinct from ``core.shader_performance_profiling``, the existing
static-heuristic scan of ``.shader`` file text (sampler/pass/loop counts,
no real hardware data) -- this feature is its live-GPU-data counterpart,
not a replacement.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from spiced.automation.finding import Finding, FindingItem
from spiced.connectors.renderdoc_analysis import ShaderGpuStats, analyze_capture
from spiced.core.hardware_simulation import HARDWARE_TIERS
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project

FEATURE_ID = "vfx.gpu_shader_profiling"

DEFAULT_TARGET_FPS = 60
DEFAULT_FRAME_BUDGET_MS = 1000.0 / DEFAULT_TARGET_FPS
# A single shader eating this fraction of the whole frame budget is already
# a lot, given a frame usually has many shaders/draws sharing it -- a
# documented, conservative default, not a hard engineering limit.
DEFAULT_BUDGET_FRACTION = 0.2
# "our low-end target" -- the Bible's own chatbox prompt example.
DEFAULT_HARDWARE_TIER = "Low-end PC"


def tier_budget_ms(
    tier: str,
    *,
    frame_budget_ms: float = DEFAULT_FRAME_BUDGET_MS,
    budget_fraction: float = DEFAULT_BUDGET_FRACTION,
) -> float:
    """The GPU-time budget (ms) a single shader shouldn't exceed on
    ``tier``, derived from ``core.hardware_simulation.HARDWARE_TIERS``'
    ``fps_factor`` -- weaker hardware gets a proportionally smaller budget,
    the same relative-scaling approach that module already uses for
    estimated fps."""
    settings = HARDWARE_TIERS.get(tier)
    if settings is None:
        raise ValueError(f"Unknown hardware tier: {tier!r}. Choose from {list(HARDWARE_TIERS)}.")
    return frame_budget_ms * settings["fps_factor"] * budget_fraction


def build_finding(
    stats: list[ShaderGpuStats],
    project_id: str,
    *,
    tier: str = DEFAULT_HARDWARE_TIER,
    budget_ms: float | None = None,
) -> Finding:
    if budget_ms is None:
        budget_ms = tier_budget_ms(tier)

    # Worst offenders first, matching the Bible's "top cost contributor" framing.
    ranked = sorted(stats, key=lambda s: s.gpu_time_ms, reverse=True)
    items: list[FindingItem] = []
    for rank, s in enumerate(ranked):
        over_budget = s.gpu_time_ms > budget_ms
        severity = "warning" if over_budget else "info"
        message = (
            f"{s.shader_name}: {s.gpu_time_ms:.2f}ms GPU time over {s.draw_call_count} draw(s)"
        )
        if over_budget:
            message += f" (over the {budget_ms:.2f}ms budget for {tier})"
        detail = {
            "shader_name": s.shader_name,
            "gpu_time_ms": round(s.gpu_time_ms, 3),
            "texture_bandwidth_bytes": s.texture_bandwidth_bytes,
            "draw_call_count": s.draw_call_count,
            "hardware_tier": tier,
            "budget_ms": round(budget_ms, 3),
        }
        if over_budget:
            detail["top_offender_rank"] = rank + 1
        items.append(
            FindingItem(asset_path=s.shader_name, severity=severity, message=message, detail=detail)
        )

    status = Finding.status_for(items)
    summary = _summarize(items, len(stats), tier)
    return Finding(
        feature_id=FEATURE_ID,
        project_id=str(project_id),
        status=status,
        summary=summary,
        items=items,
    )


def _summarize(items: list[FindingItem], shader_count: int, tier: str) -> str:
    if shader_count == 0:
        return "No shaders found in the capture."
    flagged = sum(1 for i in items if i.severity == "warning")
    if flagged:
        return f"{shader_count} shader(s) in the capture; {flagged} too expensive for {tier}."
    return f"{shader_count} shader(s) in the capture; none too expensive for {tier}."


@dataclass(frozen=True)
class GpuProfilingRunResult:
    finding: Finding
    stats: list[ShaderGpuStats]


def run_gpu_shader_profiling(
    rdc_path: str | Path,
    renderdoc_pymodules_path: str | Path,
    project_id: str,
    *,
    tier: str = DEFAULT_HARDWARE_TIER,
    budget_ms: float | None = None,
) -> GpuProfilingRunResult:
    result = analyze_capture(rdc_path, renderdoc_pymodules_path)
    if result.error is not None:
        finding = Finding(
            feature_id=FEATURE_ID,
            project_id=str(project_id),
            status="error",
            summary=result.error,
            items=[FindingItem(asset_path=str(rdc_path), severity="error", message=result.error)],
        )
        return GpuProfilingRunResult(finding=finding, stats=[])

    finding = build_finding(result.stats, project_id, tier=tier, budget_ms=budget_ms)
    return GpuProfilingRunResult(finding=finding, stats=result.stats)


class GpuShaderProfilingService:
    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def profile(
        self,
        project: Project,
        rdc_path: str | Path,
        renderdoc_pymodules_path: str | Path,
        *,
        tier: str | None = None,
    ) -> tuple[GpuProfilingRunResult, AutomationFindingRecord]:
        tier = tier or project.gpu_shader_tier or DEFAULT_HARDWARE_TIER
        budget_ms = project.gpu_shader_budget_ms
        result = run_gpu_shader_profiling(
            rdc_path, renderdoc_pymodules_path, str(project.id), tier=tier, budget_ms=budget_ms
        )
        record = self._findings.create(project.id, result.finding)
        return result, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-gpu-shader-profiling",
        description=(
            "Flag shaders too expensive for a target hardware tier, from a RenderDoc capture."
        ),
    )
    parser.add_argument("rdc_path", help="Path to a .rdc RenderDoc capture file.")
    parser.add_argument(
        "renderdoc_pymodules_path", help="Path to RenderDoc's `pymodules` directory."
    )
    parser.add_argument(
        "--tier",
        default=DEFAULT_HARDWARE_TIER,
        choices=list(HARDWARE_TIERS),
        help=f"Target hardware tier (default: {DEFAULT_HARDWARE_TIER}).",
    )
    parser.add_argument(
        "--budget-ms", type=float, default=None, help="Override the per-shader budget."
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    result = run_gpu_shader_profiling(
        args.rdc_path,
        args.renderdoc_pymodules_path,
        args.project_id,
        tier=args.tier,
        budget_ms=args.budget_ms,
    )

    if args.json:
        print(json.dumps(result.finding.as_dict(), indent=2))
    else:
        print(result.finding.summary)
        for item in result.finding.items:
            print(f"  [{item.severity}] {item.message}")

    return 1 if result.finding.status == "error" else 0


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":
    main()
