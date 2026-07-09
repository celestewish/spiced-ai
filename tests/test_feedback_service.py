import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import (
    FEEDBACK_REVIEW_RULES,
    build_feedback_review_prompt,
)
from spiced.core.feedback import FeedbackService, ProviderNotReadyError
from spiced.core.feedback_classifier import classify
from spiced.core.feedback_parser import parse_feedback
from spiced.storage.database import Database
from spiced.storage.feedback_batches import FeedbackBatchRepository
from spiced.storage.projects import ProjectRepository

CANNED_REVIEW = """Here's what players seem to be telling you.

Overall read:
A small but consistent batch.

Recurring themes:
- Movement feels great
- Players get lost after the first room

Potential bugs or technical issues:
- The pause menu appears broken

Confusion points:
- Navigation after the first room

Positive signals:
- Dash and music praised

Design preferences:
- Enemy tankiness is subjective

Prioritized next actions:
- Fix the pause menu bug (high)
- Add signposting after the first room (medium)

What I would not assume yet:
- Whether the balance complaints reflect the whole audience.
"""

MANUAL_FEEDBACK = """The dash and movement feel amazing.
The music is fantastic.
I got confused after the first room and didn't know where to go.
The pause menu is broken, it froze the game.
I fell through the platform near the start.
The enemies are too tanky and I wish there were more checkpoints.
"""


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True, reply=CANNED_REVIEW):
        self._available = available
        self._reply = reply
        self.last_prompt = None

    def is_available(self):
        return self._available

    def generate(self, prompt):
        self.last_prompt = prompt
        return AIResponse(text=self._reply, provider=self.name, model="fake-1")


def _service():
    db = Database(":memory:")
    project = ProjectRepository(db).create("Moonlit Depths", engine="Unity")
    return FeedbackService(FeedbackBatchRepository(db)), project


def test_prompt_carries_review_rules_and_human_control_language():
    parsed = parse_feedback(MANUAL_FEEDBACK)
    prompt = build_feedback_review_prompt(
        parsed, classify(parsed.entries), project_name="Moonlit Depths"
    )
    for rule in FEEDBACK_REVIEW_RULES:
        assert rule in prompt
    lower = prompt.lower()
    assert "never change their" in lower or "never change the game" in lower
    assert "you suggest, they decide" in lower


def test_preview_works_without_provider():
    service, _ = _service()
    preview = service.preview(MANUAL_FEEDBACK)
    assert preview.parsed.entry_count == 6
    assert preview.classification.counts  # heuristic categories present


def test_analyze_saves_batch_and_records_usage():
    service, project = _service()
    recorded = []
    review = service.analyze(
        FakeProvider(),
        MANUAL_FEEDBACK,
        project=project,
        source_label="Playtest 1",
        record_usage=recorded.append,
    )
    assert review.parsed.entry_count == 6
    assert review.themes  # extracted from "Recurring themes:"
    assert review.action_items
    assert review.batch is not None
    assert recorded == ["fake"]
    saved = service.history(project.id)
    assert len(saved) == 1
    assert saved[0].source_label == "Playtest 1"


def test_analyze_without_project_does_not_save():
    service, _ = _service()
    review = service.analyze(FakeProvider(), MANUAL_FEEDBACK, project=None)
    assert review.batch is None


def test_analyze_raises_when_provider_unavailable():
    service, project = _service()
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), MANUAL_FEEDBACK, project=project)
