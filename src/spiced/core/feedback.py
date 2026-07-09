"""Feedback Review use-cases.

Parse pasted/imported player feedback locally, classify it with a simple local
heuristic, ask the selected provider for a calm, structured review (themes,
issues, prioritized actions), and save a compact batch. Local parsing and
classification work with no AI provider at all, so the developer can always
preview what Spiced detected before spending a prompt.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_feedback_review_prompt
from spiced.core.feedback_classifier import FeedbackClassification, classify
from spiced.core.feedback_parser import ParsedFeedback, parse_feedback
from spiced.storage.feedback_batches import FeedbackBatch, FeedbackBatchRepository
from spiced.storage.projects import Project

SOURCE_PASTE = "paste"
SOURCE_FILE = "file"


@dataclass(frozen=True)
class FeedbackPreview:
    parsed: ParsedFeedback
    classification: FeedbackClassification


@dataclass(frozen=True)
class FeedbackReview:
    parsed: ParsedFeedback
    classification: FeedbackClassification
    response_text: str
    provider: str
    themes: list[str]
    issues: list[str]
    action_items: list[str]
    batch: FeedbackBatch | None


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class FeedbackService:
    """Local feedback parsing/classification plus AI-assisted review."""

    def __init__(self, batches: FeedbackBatchRepository) -> None:
        self._batches = batches

    # --- Local-only (no provider needed) ----------------------------------

    def preview(self, feedback_text: str, filename: str | None = None) -> FeedbackPreview:
        parsed = parse_feedback(feedback_text, filename=filename)
        return FeedbackPreview(parsed=parsed, classification=classify(parsed.entries))

    # --- Parse + classify + review ----------------------------------------

    def analyze(
        self,
        provider: AIProvider,
        feedback_text: str,
        *,
        project: Project | None = None,
        source_type: str = SOURCE_PASTE,
        source_label: str | None = None,
        source_filename: str | None = None,
        record_usage=None,
    ) -> FeedbackReview:
        """Parse + classify locally, ask the provider for a review, and save a batch.

        ``record_usage`` is called with the provider name after a successful
        reply so the usage counter can increment.
        """
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. You can still preview "
                "the locally parsed feedback and category counts without it. For AI review, "
                "add its API key to a local .env file (see .env.example), or switch to the "
                "Mock provider in Settings."
            )

        parsed = parse_feedback(feedback_text, filename=source_filename)
        classification = classify(parsed.entries)
        prompt = build_feedback_review_prompt(
            parsed,
            classification,
            project_name=project.name if project else None,
            source_label=source_label,
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        themes = _extract_bullets(response.text, "recurring themes")
        issues = _extract_bullets(response.text, "potential bugs")
        action_items = _extract_bullets(response.text, "prioritized next actions")

        batch = None
        if project is not None:
            batch = self._batches.create(
                project_id=project.id,
                source_type=source_type,
                entry_count=parsed.entry_count,
                source_label=source_label,
                source_filename=source_filename,
                raw_excerpt=parsed.excerpt or None,
                parsed_summary={
                    **parsed.as_summary_dict(),
                    **classification.as_summary_dict(),
                },
                ai_summary=_summarize(response.text),
                themes=themes or None,
                issues=issues or None,
                action_items=action_items or None,
                provider=response.provider,
            )

        return FeedbackReview(
            parsed=parsed,
            classification=classification,
            response_text=response.text,
            provider=response.provider,
            themes=themes,
            issues=issues,
            action_items=action_items,
            batch=batch,
        )

    def history(self, project_id: int, limit: int = 20) -> list[FeedbackBatch]:
        return self._batches.list_for_project(project_id, limit=limit)


def _summarize(response_text: str, limit: int = 240) -> str:
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.lower().startswith("here's what"):
            return stripped[:limit]
    return response_text.strip()[:limit]


def _extract_bullets(response_text: str, heading: str) -> list[str]:
    """Pull the bullet list under a heading that starts with ``heading``."""
    bullets: list[str] = []
    capturing = False
    for line in response_text.splitlines():
        stripped = line.strip()
        if not capturing:
            if stripped.lower().startswith(heading):
                capturing = True
            continue
        if stripped.startswith(("-", "*", "•")):
            bullets.append(stripped.lstrip("-*• ").strip())
        elif stripped.endswith(":"):
            break
    return bullets
