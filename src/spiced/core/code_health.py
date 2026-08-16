"""Code Health Dashboard use-case.

Computes deterministic metrics on one pasted/imported script (works fully
offline, no provider needed), then optionally asks the selected provider to
turn them into a calm, non-judgmental, prioritized summary.

Phase D folds two more, project-wide checks into this same dashboard —
Naming/Organization Consistency and Dead Reference Detection — reusing the
recursive ``Assets/`` scan in ``connectors.unity_scan`` (shared with the
Asset Optimization Sweep). Both stay purely local/deterministic, matching the
spec's "flags outliers, never enforces" and "best-effort, not certainty"
framing: no AI call, no new report table, computed fresh each time since a
recursive folder walk is cheap and always reflects the project's current state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_code_health_prompt
from spiced.connectors.unity_scan import (
    NamingConventionResult,
    ReferenceScanResult,
    infer_naming_convention,
    scan_references,
)
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


class NoUnityFolderError(RuntimeError):
    """Raised when the project has no connected folder to scan."""


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
        on_chunk: Callable[[str], None] | None = None,
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
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
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

    # --- Naming Consistency + Dead Reference Detection (Phase D) -----------
    # Project-wide, read-only, deterministic — no AI call, see module docstring.

    def scan_naming_convention(self, project: Project) -> NamingConventionResult:
        if not project.path:
            raise NoUnityFolderError(
                "Connect a Unity folder for this project first (Projects screen)."
            )
        return infer_naming_convention(project.path)

    def scan_dead_references(self, project: Project) -> ReferenceScanResult:
        if not project.path:
            raise NoUnityFolderError(
                "Connect a Unity folder for this project first (Projects screen)."
            )
        return scan_references(project.path)


def _summarize(response_text: str, limit: int = 240) -> str:
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.lower().startswith("here's"):
            return stripped[:limit]
    return response_text.strip()[:limit]
