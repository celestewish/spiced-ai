"""Feedback Review use-cases.

Parse pasted/imported player feedback locally, classify it with a simple local
heuristic, ask the selected provider for a calm, structured review (themes,
issues, prioritized actions), and save a compact batch. Local parsing and
classification work with no AI provider at all, so the developer can always
preview what Spiced detected before spending a prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_feedback_review_prompt
from spiced.core.feedback_classifier import FeedbackClassification, classify
from spiced.core.feedback_parser import ParsedFeedback, parse_feedback
from spiced.core.feedback_tasks import draft_task_text
from spiced.storage.feedback_batches import FeedbackBatch, FeedbackBatchRepository
from spiced.storage.feedback_tasks import FeedbackTask, FeedbackTaskRepository
from spiced.storage.projects import Project

SOURCE_PASTE = "paste"
SOURCE_FILE = "file"


@dataclass(frozen=True)
class ThemeCard:
    category: str
    count: int
    percentage: float
    representative_text: str | None


@dataclass(frozen=True)
class FeedbackPreview:
    parsed: ParsedFeedback
    classification: FeedbackClassification

    @property
    def theme_cards(self) -> list[ThemeCard]:
        return _build_theme_cards(self.parsed, self.classification)


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

    @property
    def theme_cards(self) -> list[ThemeCard]:
        return _build_theme_cards(self.parsed, self.classification)


def _build_theme_cards(
    parsed: ParsedFeedback, classification: FeedbackClassification
) -> list[ThemeCard]:
    """Category cards sorted by frequency, each with one representative example."""
    total = sum(classification.counts.values())
    if total == 0:
        return []
    representative: dict[str, str] = {}
    for entry, label in zip(parsed.entries, classification.labels, strict=True):
        representative.setdefault(label, entry.text)
    cards = [
        ThemeCard(
            category=category,
            count=count,
            percentage=round(100 * count / total, 1),
            representative_text=representative.get(category),
        )
        for category, count in classification.counts.items()
    ]
    return sorted(cards, key=lambda c: c.count, reverse=True)


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class FeedbackService:
    """Local feedback parsing/classification plus AI-assisted review."""

    def __init__(
        self, batches: FeedbackBatchRepository, tasks: FeedbackTaskRepository | None = None
    ) -> None:
        self._batches = batches
        self._tasks = tasks

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
        team_mode: bool = False,
        team_members: list[str] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> FeedbackReview:
        """Parse + classify locally, ask the provider for a review, and save a batch.

        ``record_usage`` is called with the provider name after a successful
        reply so the usage counter can increment. ``team_mode``/``team_members``
        are Small-Team Mode context (Phase B); left at their defaults, behavior
        is identical to Solo-Dev Mode.
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
            team_mode=team_mode,
            team_members=team_members,
        )
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
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

    # --- Feedback-to-task drafts (no provider needed) ----------------------

    def draft_task(
        self, project_id: int, category: str, representative_text: str, batch_id: int | None = None
    ) -> FeedbackTask:
        if self._tasks is None:
            raise RuntimeError("Feedback-to-task drafting is not configured.")
        text = draft_task_text(category, representative_text or "")
        return self._tasks.create(project_id, category, text, batch_id=batch_id)

    def list_tasks(self, project_id: int) -> list[FeedbackTask]:
        return self._tasks.list_for_project(project_id) if self._tasks else []

    def update_task(self, task_id: int, text: str) -> FeedbackTask:
        if self._tasks is None:
            raise RuntimeError("Feedback-to-task drafting is not configured.")
        return self._tasks.update_text(task_id, text)

    def set_task_status(self, task_id: int, status: str) -> FeedbackTask:
        if self._tasks is None:
            raise RuntimeError("Feedback-to-task drafting is not configured.")
        return self._tasks.set_status(task_id, status)

    def delete_task(self, task_id: int) -> None:
        if self._tasks is not None:
            self._tasks.delete(task_id)


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
