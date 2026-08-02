import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import PERFORMANCE_REVIEW_RULES, build_performance_review_prompt
from spiced.core.performance import PerformanceService, ProviderNotReadyError
from spiced.core.performance_parser import parse_performance_data
from spiced.storage.database import Database
from spiced.storage.performance_reports import PerformanceReportRepository
from spiced.storage.projects import ProjectRepository

PERF_TEXT = "Waterfall Area: fps=25, memory=900MB, load=6.5s\nTown: fps=58, memory=400MB\n"

CANNED = """Here's what the performance numbers suggest.

Result summary:
- Samples read: 2

Spikes worth a look:
- Waterfall Area fps drop, possibly too many particle systems

Target-hardware notes:
- No hardware simulation requested.

Suggested checks:
- Profile the waterfall area

What I would not assume yet:
- Root cause
"""


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True, reply=CANNED):
        self._available = available
        self._reply = reply

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=self._reply, provider=self.name, model="fake-1")


def _service():
    db = Database(":memory:")
    project = ProjectRepository(db).create("Moonlit Depths", engine="Unity")
    return PerformanceService(PerformanceReportRepository(db)), project


def test_prompt_carries_rules_and_never_ran_language():
    parsed = parse_performance_data(PERF_TEXT)
    prompt = build_performance_review_prompt(parsed, project_name="Moonlit Depths")
    for rule in PERFORMANCE_REVIEW_RULES:
        assert rule in prompt
    assert "never claim you ran a profiler" in prompt.lower()


def test_analyze_saves_report_with_target_hardware():
    service, project = _service()
    recorded = []
    review = service.analyze(
        FakeProvider(), PERF_TEXT, project=project, target_hardware="Low-end PC",
        record_usage=recorded.append,
    )
    assert review.simulation is not None
    assert review.report is not None
    assert review.report.target_hardware == "Low-end PC"
    assert recorded == ["fake"]
    assert service.history(project.id)[0].id == review.report.id


def test_analyze_without_target_hardware_has_no_simulation():
    service, project = _service()
    review = service.analyze(FakeProvider(), PERF_TEXT, project=project)
    assert review.simulation is None


def test_analyze_without_project_does_not_save():
    service, _ = _service()
    review = service.analyze(FakeProvider(), PERF_TEXT, project=None)
    assert review.report is None


def test_analyze_raises_when_provider_unavailable():
    service, project = _service()
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), PERF_TEXT, project=project)
