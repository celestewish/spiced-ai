"""Contract/License Checklist use-case (Phase H, section 7 part 2, Stretch tier).

The developer pastes/imports a contract or license document (plain text or
Markdown -- see the scope note below) and the AI flags common gaps/red flags
as a "things to double check" list. This is explicitly, repeatedly **not
legal advice** -- see ``build_contract_checklist_prompt``'s rules and
response format, and the UI copy this service's callers are expected to
show alongside it.

Format scope: a contract could be pasted directly or imported as a plain
``.txt``/``.md`` file. Unlike Phase F's Design Doc Sync, this module does
**not** add ``.docx`` extraction -- a legal document is meaningfully more
sensitive than a design doc, and adding another file-format code path (even
a small regex-based one) is scope this feature doesn't need: a developer can
always paste text copied out of Word, or export/save as plain text, before
using this feature. This is a deliberate scope-down, not an oversight.

Storage discipline: a contract is more sensitive than a debug log or
feedback batch, so this stores meaningfully less than those tables do. Only
a short preview excerpt (``PREVIEW_EXCERPT_CHARS``, far shorter than what's
sent to the AI) plus a SHA-256 hash of the full excerpt actually reviewed
are kept, alongside the AI's output -- never the full pasted document.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_contract_checklist_prompt
from spiced.storage.contract_checklist_reviews import (
    ContractChecklistReview,
    ContractChecklistReviewRepository,
)
from spiced.storage.projects import Project

# How much of the pasted/imported text is actually sent to the AI provider.
PROMPT_EXCERPT_CHARS = 6000
# How much of that excerpt is kept in the local database afterward -- far
# shorter than what's sent to the AI, per the module's storage discipline.
PREVIEW_EXCERPT_CHARS = 300

NOT_LEGAL_ADVICE_NOTICE = (
    "Not legal advice. Spiced is not a lawyer and this checklist cannot tell you whether a "
    "contract or license is safe, fair, or enforceable -- it only points out things a non-"
    "lawyer might want to ask a real lawyer about. Always have a real lawyer review anything "
    "that actually matters before you sign or rely on it."
)


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


@dataclass(frozen=True)
class ContractChecklistResult:
    response_text: str
    provider: str
    review: ContractChecklistReview | None


class ContractChecklistService:
    def __init__(self, reviews: ContractChecklistReviewRepository) -> None:
        self._reviews = reviews

    def review(
        self,
        provider: AIProvider,
        text: str,
        *,
        project: Project | None = None,
        source_filename: str | None = None,
        record_usage=None,
    ) -> ContractChecklistResult:
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings "
                "for free offline analysis."
            )

        cleaned = text.strip()
        excerpt = cleaned[:PROMPT_EXCERPT_CHARS]
        prompt = build_contract_checklist_prompt(
            excerpt, project_name=project.name if project else None
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        review = None
        if project is not None:
            review = self._reviews.create(
                project.id,
                source_filename=source_filename,
                excerpt_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                excerpt_preview=excerpt[:PREVIEW_EXCERPT_CHARS] or None,
                ai_summary=response.text,
                provider=response.provider,
            )

        return ContractChecklistResult(
            response_text=response.text, provider=response.provider, review=review
        )

    def history(self, project_id: int, limit: int = 20) -> list[ContractChecklistReview]:
        return self._reviews.list_for_project(project_id, limit=limit)
