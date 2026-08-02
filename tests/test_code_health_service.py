import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import CODE_HEALTH_RULES, build_code_health_prompt
from spiced.core.code_health import CodeHealthService, ProviderNotReadyError
from spiced.core.code_health_analyzer import analyze_code_health
from spiced.storage.code_health_reports import CodeHealthReportRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

SCRIPT = "public class C {\n    public void Foo() {\n        int x = 1;\n    }\n}\n"

CANNED = """Here's a quick code-health read on this file.

Overview:
- Lines: 5 / Functions: 1 / Average function length: 3

Worth a look (not urgent):
- Nothing major

Housekeeping:
- No TODOs

Not covered:
This only reflects this one file.
"""


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


def _service():
    db = Database(":memory:")
    project = ProjectRepository(db).create("Moonlit Depths", engine="Unity")
    return CodeHealthService(CodeHealthReportRepository(db)), project


def test_metrics_work_without_provider():
    service, _ = _service()
    metrics = service.analyze_metrics(SCRIPT)
    assert metrics.function_count == 1


def test_prompt_is_non_judgmental_and_scoped_to_one_file():
    metrics = analyze_code_health(SCRIPT)
    prompt = build_code_health_prompt(metrics, excerpt=SCRIPT, project_name="Moonlit Depths")
    for rule in CODE_HEALTH_RULES:
        assert rule in prompt
    assert "never shame" in prompt.lower()


def test_analyze_saves_metrics():
    service, project = _service()
    review = service.analyze(FakeProvider(), SCRIPT, project=project, source_filename="C.cs")
    assert review.report is not None
    assert review.report.metrics["function_count"] == 1


def test_analyze_without_project_does_not_save():
    service, _ = _service()
    review = service.analyze(FakeProvider(), SCRIPT, project=None)
    assert review.report is None


def test_analyze_raises_when_provider_unavailable():
    service, project = _service()
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), SCRIPT, project=project)
