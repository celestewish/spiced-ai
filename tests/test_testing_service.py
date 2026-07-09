import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import TEST_REVIEW_RULES, build_test_review_prompt
from spiced.core.test_result_parser import parse_test_results
from spiced.core.testing import ProviderNotReadyError, TestingService
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.test_cases import TestCaseRepository
from spiced.storage.test_runs import TestRunRepository

CANNED_REVIEW = """Here's what the test results suggest.

Result summary:
- Total detected: 5
- Passed: 2
- Failed: 2
- Skipped or blocked: 1

Main risks:
- Combat damage handling looks unreliable.

Failures to inspect:
- Player takes damage from spikes

Retest checklist:
- Re-run the spike damage scenario
- Check the health component references
- Verify the pickup collider

What I would not assume yet:
- Whether the boss test would pass.
"""

MANUAL_TEXT = """Total: 5
Passed: 2
Failed: 2
Skipped: 1
PASS Player can move
PASS Jump height
FAIL Player takes damage from spikes
FAIL Health pickup restores health
SKIPPED Boss balance
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
    service = TestingService(TestCaseRepository(db), TestRunRepository(db))
    return service, project


def test_prompt_carries_review_rules_and_forbids_running():
    parsed = parse_test_results(MANUAL_TEXT)
    prompt = build_test_review_prompt(parsed, project_name="Moonlit Depths")
    for rule in TEST_REVIEW_RULES:
        assert rule in prompt
    lower = prompt.lower()
    assert "never claim that you ran these tests" in lower
    assert "never suggest automatic changes" in lower
    assert "5" in prompt and "Player takes damage from spikes" in prompt


def test_manual_case_creation_works_without_provider():
    service, project = _service()
    # No provider is involved at all in creating and tracking test cases.
    case = service.create_case(project_id=project.id, title="Player takes damage")
    updated = service.set_status(case.id, "Fail", "no damage applied")
    assert updated.status == "Fail"
    assert service.list_cases(project.id)[0].failure_note == "no damage applied"


def test_analyze_saves_run_and_records_usage():
    service, project = _service()
    recorded = []
    review = service.analyze(
        FakeProvider(),
        MANUAL_TEXT,
        project=project,
        record_usage=recorded.append,
    )
    assert review.parsed.total == 5
    assert review.parsed.failed == 2
    assert review.run is not None
    assert review.retest_checklist  # extracted from "Retest checklist:"
    assert recorded == ["fake"]
    # The saved run keeps only an excerpt/summary, not the full output.
    assert service.history(project.id)[0].parsed_summary["failed"] == 2


def test_update_and_delete_case_through_service():
    service, project = _service()
    case = service.create_case(project_id=project.id, title="Original", category="UI")
    edited = service.update_case(
        case.id, title="Edited", category="Gameplay", priority="High", status="Blocked"
    )
    assert edited.title == "Edited"
    assert edited.category == "Gameplay"
    assert edited.status == "Blocked"

    service.delete_case(case.id)
    assert service.list_cases(project.id) == []


def test_delete_case_keeps_test_run_history():
    service, project = _service()
    service.analyze(FakeProvider(), MANUAL_TEXT, project=project)
    case = service.create_case(project_id=project.id, title="Doomed")
    service.delete_case(case.id)
    # The run recorded before the delete is still there.
    assert len(service.history(project.id)) == 1


def test_analyze_without_project_does_not_save():
    service, _ = _service()
    review = service.analyze(FakeProvider(), MANUAL_TEXT, project=None)
    assert review.run is None


def test_analyze_raises_when_provider_unavailable():
    service, project = _service()
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), MANUAL_TEXT, project=project)
