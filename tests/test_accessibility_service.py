import json

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import ACCESSIBILITY_REVIEW_RULES, build_accessibility_review_prompt
from spiced.core.accessibility import AccessibilityService, ProviderNotReadyError
from spiced.core.accessibility_parser import parse_accessibility_data
from spiced.storage.accessibility_reports import AccessibilityReportRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

CHECKLIST = json.dumps(
    {
        "hud_elements": [{"name": "HealthBar", "foreground": "#333333", "background": "#000000"}],
        "audio_files": [{"name": "a.wav", "captioned": False}],
        "controls_remappable": False,
        "text_scaling_supported": False,
    }
)

CANNED = """Here's the accessibility pass.

Overall score: 20/100

Contrast:
- HealthBar needs a lighter foreground

Colorblind safety:
- n/a

Captions:
- 0 of 1 captioned

Controls & text scaling:
- Add remapping and scaling support

Priority fixes:
- Fix contrast
- Add captions
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
    return AccessibilityService(AccessibilityReportRepository(db)), project


def test_prompt_treats_checklist_as_ground_truth():
    parsed = parse_accessibility_data(CHECKLIST)
    prompt = build_accessibility_review_prompt(parsed, project_name="Moonlit Depths")
    for rule in ACCESSIBILITY_REVIEW_RULES:
        assert rule in prompt
    assert "HealthBar" in prompt


def test_analyze_saves_score_and_findings():
    service, project = _service()
    review = service.analyze(FakeProvider(), CHECKLIST, project=project)
    assert review.report is not None
    assert review.report.score == review.parsed.score
    assert review.report.findings  # contrast/caption/controls findings present


def test_analyze_without_project_does_not_save():
    service, _ = _service()
    review = service.analyze(FakeProvider(), CHECKLIST, project=None)
    assert review.report is None


def test_analyze_raises_when_provider_unavailable():
    service, project = _service()
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), CHECKLIST, project=project)
