"""Accessibility Pass use-case.

Runs a deterministic checklist (WCAG contrast, a colorblind simulation, caption
coverage, and two yes/no flags) against a pasted/imported description of the
build's UI and audio, then asks the selected provider to turn it into a scored,
plain-language write-up with specific fixes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_accessibility_review_prompt
from spiced.core.accessibility_parser import ParsedAccessibility, parse_accessibility_data
from spiced.storage.accessibility_reports import AccessibilityReport, AccessibilityReportRepository
from spiced.storage.projects import Project

SOURCE_PASTE = "paste"
SOURCE_FILE = "file"


@dataclass(frozen=True)
class AccessibilityReview:
    parsed: ParsedAccessibility
    response_text: str
    provider: str
    report: AccessibilityReport | None


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class AccessibilityService:
    def __init__(self, reports: AccessibilityReportRepository) -> None:
        self._reports = reports

    def parse(self, accessibility_text: str) -> ParsedAccessibility:
        return parse_accessibility_data(accessibility_text)

    def analyze(
        self,
        provider: AIProvider,
        accessibility_text: str,
        *,
        project: Project | None = None,
        source_type: str = SOURCE_PASTE,
        source_filename: str | None = None,
        record_usage=None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> AccessibilityReview:
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in "
                "Settings for free offline analysis."
            )

        parsed = self.parse(accessibility_text)
        prompt = build_accessibility_review_prompt(
            parsed, project_name=project.name if project else None
        )
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
            response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        report = None
        if project is not None:
            summary = parsed.as_summary_dict()
            report = self._reports.create(
                project_id=project.id,
                source_type=source_type,
                source_filename=source_filename,
                raw_excerpt=parsed.excerpt or None,
                parsed_summary=summary,
                ai_summary=_summarize(response.text),
                findings=summary["findings"] or None,
                score=parsed.score,
                provider=response.provider,
            )

        return AccessibilityReview(
            parsed=parsed, response_text=response.text, provider=response.provider, report=report
        )

    def history(self, project_id: int, limit: int = 20) -> list[AccessibilityReport]:
        return self._reports.list_for_project(project_id, limit=limit)


def _summarize(response_text: str, limit: int = 240) -> str:
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.lower().startswith("here's what"):
            return stripped[:limit]
    return response_text.strip()[:limit]
