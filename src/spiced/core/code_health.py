"""Code Health Dashboard use-case.

Computes deterministic metrics on one pasted/imported script (works fully
offline, no provider needed), then optionally asks the selected provider to
turn them into a calm, non-judgmental, prioritized summary.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_code_health_prompt
from spiced.core.code_health_analyzer import CodeHealthMetrics, analyze_code_health
from spiced.storage.code_health_reports import CodeHealthReport, CodeHealthReportRepository
from spiced.storage.projects import Project

MAX_EXCERPT_CHARS = 2000


@dataclass(frozen=True)
class CodeHealthReview:
    metrics: CodeHealthMetrics
    response_text: str
    provider: str
    report: CodeHealthReport | None


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class CodeHealthService:
    def __init__(self, reports: CodeHealthReportRepository) -> None:
        self._reports = reports

    def analyze_metrics(self, code_text: str) -> CodeHealthMetrics:
        """Local-only metrics. Free, offline, no provider needed."""
        return analyze_code_health(code_text)

    def analyze(
        self,
        provider: AIProvider,
        code_text: str,
        *,
        project: Project | None = None,
        source_filename: str | None = None,
        record_usage=None,
    ) -> CodeHealthReview:
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. You can still see the "
                "local metrics without it. For a written summary, add its API key to a local "
                ".env file (see .env.example), or switch to the Mock provider in Settings."
            )

        metrics = self.analyze_metrics(code_text)
        excerpt = code_text.strip()[:MAX_EXCERPT_CHARS]
        prompt = build_code_health_prompt(
            metrics, excerpt=excerpt, project_name=project.name if project else None
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        report = None
        if project is not None:
            report = self._reports.create(
                project_id=project.id,
                source_filename=source_filename,
                raw_excerpt=excerpt or None,
                metrics=metrics.as_summary_dict(),
                ai_summary=_summarize(response.text),
                provider=response.provider,
            )

        return CodeHealthReview(
            metrics=metrics, response_text=response.text, provider=response.provider, report=report
        )

    def history(self, project_id: int, limit: int = 20) -> list[CodeHealthReport]:
        return self._reports.list_for_project(project_id, limit=limit)


def _summarize(response_text: str, limit: int = 240) -> str:
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.lower().startswith("here's"):
            return stripped[:limit]
    return response_text.strip()[:limit]
