"""Version-Aware Suggestions use-case.

Scanning for deprecated Unity API calls is fully deterministic and works with
no AI provider at all — the same offline-first pattern as manual test cases.
The AI step is optional and only adds narrative framing on top of the exact,
already-correct hits.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_version_check_prompt
from spiced.core.version_check_parser import ParsedVersionCheck, scan_for_deprecated_apis
from spiced.storage.projects import Project
from spiced.storage.version_check_reports import VersionCheckReport, VersionCheckReportRepository


@dataclass(frozen=True)
class VersionCheckReview:
    parsed: ParsedVersionCheck
    response_text: str
    provider: str
    report: VersionCheckReport | None


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class VersionCheckService:
    def __init__(self, reports: VersionCheckReportRepository) -> None:
        self._reports = reports

    def scan(self, code_text: str) -> ParsedVersionCheck:
        """Local-only deprecated-API scan. Free, offline, no provider needed."""
        return scan_for_deprecated_apis(code_text)

    def analyze(
        self,
        provider: AIProvider,
        code_text: str,
        *,
        project: Project | None = None,
        source_filename: str | None = None,
        record_usage=None,
    ) -> VersionCheckReview:
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. You can still run the "
                "local scan without it. For a narrative review, add its API key to a local "
                ".env file (see .env.example), or switch to the Mock provider in Settings."
            )

        parsed = self.scan(code_text)
        prompt = build_version_check_prompt(parsed, project_name=project.name if project else None)
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        report = None
        if project is not None:
            summary = parsed.as_summary_dict()
            report = self._reports.create(
                project_id=project.id,
                source_filename=source_filename,
                raw_excerpt=parsed.excerpt or None,
                hits=summary["hits"] or None,
                ai_summary=_summarize(response.text),
                provider=response.provider,
            )

        return VersionCheckReview(
            parsed=parsed, response_text=response.text, provider=response.provider, report=report
        )

    def history(self, project_id: int, limit: int = 20) -> list[VersionCheckReport]:
        return self._reports.list_for_project(project_id, limit=limit)


def _summarize(response_text: str, limit: int = 240) -> str:
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.lower().startswith("here's"):
            return stripped[:limit]
    return response_text.strip()[:limit]
