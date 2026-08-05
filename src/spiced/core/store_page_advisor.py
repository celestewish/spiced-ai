"""Store Page Optimization Advisor use-case (Phase G, section 7, Phase 2 tier).

The developer pastes or imports a Steam/itch store page draft (title, short
description, tags — plain text or a simple structured paste). Spiced reviews
it against a small set of documented best practices (a clear hook in the
first line, readable/relevant tag choices, common mistakes) via the AI
provider and returns specific suggestions — explicitly framed as
suggestions, never a guarantee of sales. Spiced never fetches, scrapes, or
publishes anything on a store page itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_store_page_prompt
from spiced.storage.projects import Project
from spiced.storage.store_page_reviews import StorePageReview, StorePageReviewRepository

MAX_DESCRIPTION_CHARS = 4000


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


@dataclass(frozen=True)
class StorePageDraft:
    title: str
    description: str
    tags: list[str]


@dataclass(frozen=True)
class StorePageReviewResult:
    draft: StorePageDraft
    response_text: str
    provider: str
    review: StorePageReview | None


def parse_tags(tags_text: str) -> list[str]:
    """Split a comma- or newline-separated tags field into a clean list."""
    normalized = tags_text.replace("\n", ",")
    return [t.strip() for t in normalized.split(",") if t.strip()]


class StorePageAdvisorService:
    def __init__(self, reviews: StorePageReviewRepository) -> None:
        self._reviews = reviews

    def review(
        self,
        provider: AIProvider,
        title: str,
        description: str,
        tags_text: str,
        *,
        project: Project | None = None,
        record_usage=None,
    ) -> StorePageReviewResult:
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )
        draft = StorePageDraft(
            title=title.strip(),
            description=description.strip()[:MAX_DESCRIPTION_CHARS],
            tags=parse_tags(tags_text),
        )

        prompt = build_store_page_prompt(
            title=draft.title,
            description=draft.description,
            tags=draft.tags,
            project_name=project.name if project else None,
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        review = None
        if project is not None:
            review = self._reviews.create(
                project_id=project.id,
                title=draft.title or None,
                description=draft.description or None,
                tags_json=json.dumps(draft.tags),
                ai_summary=response.text,
                provider=response.provider,
            )
        return StorePageReviewResult(
            draft=draft, response_text=response.text, provider=response.provider, review=review
        )

    def history(self, project_id: int, limit: int = 20) -> list[StorePageReview]:
        return self._reviews.list_for_project(project_id, limit=limit)
