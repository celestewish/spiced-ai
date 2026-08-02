from spiced.core.feedback_classifier import BUG, PRAISE
from spiced.core.feedback_tasks import draft_task_text


def test_bug_category_uses_investigate_verb():
    text = draft_task_text(BUG, "the game crashes near the boss")
    assert text.startswith("Investigate bug or technical issue")
    assert "the game crashes near the boss" in text


def test_praise_category_uses_note_verb():
    text = draft_task_text(PRAISE, "loved the music")
    assert text.startswith("Note (positive) feedback on praise")


def test_unknown_category_falls_back_to_default_verb():
    text = draft_task_text("Some Category", "example text")
    assert text.startswith("Follow up on some category")


def test_long_snippet_is_truncated():
    long_text = "x" * 200
    text = draft_task_text(BUG, long_text)
    assert "…" in text
    assert len(text) < 200 + 60


def test_empty_representative_text_still_produces_a_task():
    text = draft_task_text(BUG, "")
    assert text  # non-empty, no dangling quotes
    assert '""' not in text
