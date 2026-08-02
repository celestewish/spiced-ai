"""Feedback-to-Task Converter: draft a short task from a feedback theme.

Purely a local template — no AI call. Spiced drafts a starting point the
developer can accept, edit, or export to their own tracker; it never manages
a task list on its own.
"""

from __future__ import annotations

from spiced.core.feedback_classifier import (
    BALANCE,
    BUG,
    CONFUSION,
    FEATURE,
    PERFORMANCE,
    PRAISE,
    PREFERENCE,
    UIUX,
)

MAX_SNIPPET_CHARS = 100

_VERB_BY_CATEGORY = {
    BUG: "Investigate",
    PERFORMANCE: "Investigate performance for",
    CONFUSION: "Clarify",
    BALANCE: "Review balance for",
    UIUX: "Review UI for",
    FEATURE: "Consider adding",
    PRAISE: "Note (positive) feedback on",
    PREFERENCE: "Consider (subjective) feedback on",
}
_DEFAULT_VERB = "Follow up on"


def _snippet(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) > MAX_SNIPPET_CHARS:
        cleaned = cleaned[: MAX_SNIPPET_CHARS - 1].rstrip() + "…"
    return cleaned


def draft_task_text(category: str, representative_text: str) -> str:
    """Draft a short, editable task line from a feedback category + example."""
    verb = _VERB_BY_CATEGORY.get(category, _DEFAULT_VERB)
    snippet = _snippet(representative_text)
    if snippet:
        return f'{verb} {category.lower()} — "{snippet}" (from player feedback)'
    return f"{verb} {category.lower()} (from player feedback)"
