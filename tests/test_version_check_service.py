import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import VERSION_CHECK_RULES, build_version_check_prompt
from spiced.core.version_check import ProviderNotReadyError, VersionCheckService
from spiced.core.version_check_parser import scan_for_deprecated_apis
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.version_check_reports import VersionCheckReportRepository

CODE = "var e = FindObjectOfType<Enemy>();\nrb.velocity = Vector3.zero;\n"

CANNED = """Here's the outdated-API review.

Findings:
- Line 1: FindObjectOfType -> FindFirstObjectByType, faster by default

If clean:


What this does not cover:
This only checks a curated list.
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
    return VersionCheckService(VersionCheckReportRepository(db)), project


def test_scan_works_without_provider():
    service, _ = _service()
    parsed = service.scan(CODE)
    assert parsed.has_hits


def test_prompt_carries_rules_and_curated_disclaimer():
    parsed = scan_for_deprecated_apis(CODE)
    prompt = build_version_check_prompt(parsed, project_name="Moonlit Depths")
    for rule in VERSION_CHECK_RULES:
        assert rule in prompt
    assert "curated" in prompt.lower()


def test_analyze_saves_hits():
    service, project = _service()
    review = service.analyze(FakeProvider(), CODE, project=project, source_filename="Enemy.cs")
    assert review.report is not None
    assert review.report.hits
    assert service.history(project.id)[0].source_filename == "Enemy.cs"


def test_analyze_without_project_does_not_save():
    service, _ = _service()
    review = service.analyze(FakeProvider(), CODE, project=None)
    assert review.report is None


def test_analyze_raises_when_provider_unavailable():
    service, project = _service()
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), CODE, project=project)
