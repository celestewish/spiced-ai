"""Performance & Profiling Reports, plus Cross-Platform Test Simulation.

Two responsibilities, both building on numbers the developer already gathered:

1. Parse pasted/imported performance data locally (deterministic) and flag fps/
   memory/load-time spikes.
2. Optionally layer a target-hardware simulation on top (a documented estimate,
   not a real device test), then ask the selected provider for a calm,
   plain-language interpretation of both.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_performance_review_prompt
from spiced.core.hardware_simulation import HardwareSimulationResult, simulate_hardware
from spiced.core.performance_parser import ParsedPerformance, parse_performance_data
from spiced.storage.performance_reports import PerformanceReport, PerformanceReportRepository
from spiced.storage.projects import Project

SOURCE_PASTE = "paste"
SOURCE_FILE = "file"


@dataclass(frozen=True)
class PerformanceReview:
    parsed: ParsedPerformance
    simulation: HardwareSimulationResult | None
    response_text: str
    provider: str
    report: PerformanceReport | None


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class PerformanceService:
    """Local performance parsing/simulation plus AI-assisted interpretation."""

    def __init__(self, reports: PerformanceReportRepository) -> None:
        self._reports = reports

    def parse(self, performance_text: str) -> ParsedPerformance:
        return parse_performance_data(performance_text)

    def simulate(self, parsed: ParsedPerformance, tier: str) -> HardwareSimulationResult | None:
        return simulate_hardware(parsed, tier)

    def analyze(
        self,
        provider: AIProvider,
        performance_text: str,
        *,
        project: Project | None = None,
        target_hardware: str | None = None,
        source_type: str = SOURCE_PASTE,
        source_filename: str | None = None,
        record_usage=None,
    ) -> PerformanceReview:
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in "
                "Settings for free offline analysis."
            )

        parsed = self.parse(performance_text)
        simulation = self.simulate(parsed, target_hardware) if target_hardware else None
        prompt = build_performance_review_prompt(
            parsed, project_name=project.name if project else None, simulation=simulation
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        report = None
        if project is not None:
            report = self._reports.create(
                project_id=project.id,
                source_type=source_type,
                source_filename=source_filename,
                target_hardware=target_hardware,
                raw_excerpt=parsed.excerpt or None,
                parsed_summary=parsed.as_summary_dict(),
                ai_summary=_summarize(response.text),
                spikes=parsed.as_summary_dict()["spikes"] or None,
                provider=response.provider,
            )

        return PerformanceReview(
            parsed=parsed,
            simulation=simulation,
            response_text=response.text,
            provider=response.provider,
            report=report,
        )

    def history(self, project_id: int, limit: int = 20) -> list[PerformanceReport]:
        return self._reports.list_for_project(project_id, limit=limit)


def _summarize(response_text: str, limit: int = 240) -> str:
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.lower().startswith("here's what"):
            return stripped[:limit]
    return response_text.strip()[:limit]
