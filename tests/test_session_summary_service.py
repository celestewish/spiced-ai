"""SessionSummaryService tests: window gathering, provider call, and persistence.

Mirrors test_debugging_service.py's pattern — a fake provider, a real
in-memory Database, and the real repositories/services this service composes
(TestingService, FeedbackService) so the window-gathering logic is exercised
against real storage rather than mocks.
"""

from __future__ import annotations

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.core.feedback import FeedbackService
from spiced.core.regression import RegressionService
from spiced.core.session_summary import ProviderNotReadyError, SessionSummaryService
from spiced.core.testing import TestingService
from spiced.storage.database import Database
from spiced.storage.feedback_batches import FeedbackBatchRepository
from spiced.storage.feedback_tasks import FeedbackTaskRepository
from spiced.storage.known_issues import KnownIssueRepository
from spiced.storage.projects import ProjectRepository
from spiced.storage.session_summaries import SessionSummaryRepository
from spiced.storage.test_cases import TestCaseRepository
from spiced.storage.test_runs import TestRunRepository

CANNED_RECAP = """Session recap.

Tested:
- Test run: 3 passed / 0 failed

Fixed:
- Pause menu freeze

Still open:
- Feedback task: Investigate the jump bug

One-line summary:
Quiet session, mostly cleanup.
"""


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True, reply=CANNED_RECAP):
        self._available = available
        self._reply = reply
        self.last_prompt = None

    def is_available(self):
        return self._available

    def generate(self, prompt):
        self.last_prompt = prompt
        return AIResponse(text=self._reply, provider=self.name, model="fake-1")


def _setup():
    db = Database(":memory:")
    project = ProjectRepository(db).create("Moonlit Depths", engine="Unity")
    regression = RegressionService(KnownIssueRepository(db))
    testing = TestingService(TestCaseRepository(db), TestRunRepository(db), regression)
    feedback = FeedbackService(FeedbackBatchRepository(db), FeedbackTaskRepository(db))
    service = SessionSummaryService(SessionSummaryRepository(db), testing, feedback)
    return service, testing, feedback, project


EARLY = "2026-08-03 08:00:00"


def test_gather_window_empty_when_nothing_recorded():
    service, _testing, _feedback, project = _setup()
    window = service.gather_window(project.id, EARLY)
    assert window.since == EARLY
    assert window.is_empty


def test_gather_window_picks_up_open_known_issues():
    service, testing, _feedback, project = _setup()
    testing.analyze(
        FakeProvider(reply="Result summary:\n- Total detected: 1"),
        "FAIL: Something broke\n",
        project=project,
    )
    issues = testing.known_issues(project.id)
    assert issues and issues[0].status == "open"

    window = service.gather_window(project.id, EARLY)
    assert any("Something broke" in item for item in window.open_items)


def test_gather_window_picks_up_pending_feedback_tasks():
    service, _testing, feedback, project = _setup()
    feedback.draft_task(project.id, "Bug or technical issue", "the pause menu is broken")
    window = service.gather_window(project.id, EARLY)
    assert any("pause menu" in item for item in window.open_items)


def test_summarize_saves_summary_and_records_usage():
    service, _testing, feedback, project = _setup()
    feedback.draft_task(project.id, "Bug or technical issue", "the jump bug")
    recorded = []
    result = service.summarize(
        FakeProvider(), project, EARLY, record_usage=recorded.append
    )
    assert result.summary.ai_summary == CANNED_RECAP
    assert result.summary.started_at == EARLY
    assert result.summary.synced_to_team is False
    assert recorded == ["fake"]
    assert service.history(project.id)[0].id == result.summary.id


def test_second_summary_windows_off_the_first_ended_at():
    service, _testing, feedback, project = _setup()
    first = service.summarize(FakeProvider(), project, EARLY)
    feedback.draft_task(project.id, "Bug or technical issue", "a new bug found after summary 1")
    second_window = service.gather_window(project.id, EARLY)
    assert second_window.since == first.summary.ended_at
    assert any("new bug found after summary 1" in item for item in second_window.open_items)


def test_summarize_raises_when_provider_unavailable():
    service, _testing, _feedback, project = _setup()
    with pytest.raises(ProviderNotReadyError):
        service.summarize(FakeProvider(available=False), project, EARLY)


def test_mark_synced_flips_flag():
    service, _testing, _feedback, project = _setup()
    result = service.summarize(FakeProvider(), project, EARLY)
    assert result.summary.synced_to_team is False
    updated = service.mark_synced(result.summary.id)
    assert updated.synced_to_team is True
