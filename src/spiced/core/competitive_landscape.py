"""Competitive Landscape Scan use-case (Phase H, section 7 part 2, Phase 2 tier).

Scope decision: a local desktop app has no realistic way to reach live,
current market data (Steam/itch pricing, review counts, reception) without a
new API integration this session shouldn't add -- there is no public,
scrape-free storefront API suited to this. Instead this is an AI-assisted
feature that works from the model's own general knowledge: the developer
describes their game and the AI suggests comparable existing titles and
general positioning thoughts. Explicitly and visibly labeled as
approximate/potentially outdated, never live market data -- see
``build_competitive_landscape_prompt``'s rules and response format, which
both require a "verify current details yourself" caveat. Framed to inform,
never to discourage, per spec.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_competitive_landscape_prompt
from spiced.storage.competitive_landscape_reports import (
    CompetitiveLandscapeReport,
    CompetitiveLandscapeReportRepository,
)
from spiced.storage.projects import Project

MAX_DESCRIPTION_CHARS = 4000

NOT_LIVE_DATA_NOTICE = (
    "Approximate, from general knowledge only -- not live market data. Spiced has no live "
    "connection to any storefront. Verify current pricing, review counts, and positioning "
    "yourself before drawing conclusions."
)


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


@dataclass(frozen=True)
class CompetitiveLandscapeResult:
    response_text: str
    provider: str
    report: CompetitiveLandscapeReport | None


class CompetitiveLandscapeService:
    def __init__(self, reports: CompetitiveLandscapeReportRepository) -> None:
        self._reports = reports

    def analyze(
        self,
        provider: AIProvider,
        description: str,
        *,
        project: Project | None = None,
        record_usage=None,
    ) -> CompetitiveLandscapeResult:
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )

        excerpt = description.strip()[:MAX_DESCRIPTION_CHARS]
        prompt = build_competitive_landscape_prompt(
            excerpt, project_name=project.name if project else None
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        report = None
        if project is not None:
            report = self._reports.create(
                project.id,
                description_excerpt=excerpt or None,
                ai_summary=response.text,
                provider=response.provider,
            )

        return CompetitiveLandscapeResult(
            response_text=response.text, provider=response.provider, report=report
        )

    def history(self, project_id: int, limit: int = 20) -> list[CompetitiveLandscapeReport]:
        return self._reports.list_for_project(project_id, limit=limit)
