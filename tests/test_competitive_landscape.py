"""Tests for core.competitive_landscape: prompt building + review orchestration."""

from __future__ import annotations

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import (
    COMPETITIVE_LANDSCAPE_RULES,
    build_competitive_landscape_prompt,
)
from spiced.core.competitive_landscape import (
    MAX_DESCRIPTION_CHARS,
    CompetitiveLandscapeService,
    ProviderNotReadyError,
)
from spiced.storage.competitive_landscape_reports import CompetitiveLandscapeReportRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

CANNED = "Approximate read, not live market data — verify anything specific yourself."


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


def test_prompt_includes_all_rules_and_the_description():
    prompt = build_competitive_landscape_prompt(
        "A cozy 2D farming sim.", project_name="Moonlit Depths"
    )
    for rule in COMPETITIVE_LANDSCAPE_RULES:
        assert rule in prompt
    assert "A cozy 2D farming sim." in prompt
    assert "Moonlit Depths" in prompt


def test_prompt_labels_output_as_approximate_not_live():
    prompt = build_competitive_landscape_prompt("A roguelike.")
    assert "not live" in prompt.lower() or "approximate" in prompt.lower()
    assert "verify" in prompt.lower()


def test_prompt_handles_missing_description():
    prompt = build_competitive_landscape_prompt("   ")
    assert "(no description provided)" in prompt


def test_analyze_raises_when_provider_not_ready():
    db = Database(":memory:")
    service = CompetitiveLandscapeService(CompetitiveLandscapeReportRepository(db))
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), "A cozy sim.")


def test_analyze_caps_description_excerpt():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = CompetitiveLandscapeService(CompetitiveLandscapeReportRepository(db))

    long_description = "cozy farming sim " * (MAX_DESCRIPTION_CHARS // 10)
    result = service.analyze(FakeProvider(), long_description, project=project)

    assert result.report is not None
    assert len(result.report.description_excerpt) <= MAX_DESCRIPTION_CHARS


def test_analyze_saves_report_when_project_given():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = CompetitiveLandscapeService(CompetitiveLandscapeReportRepository(db))

    result = service.analyze(FakeProvider(), "A cozy 2D farming sim.", project=project)

    assert result.response_text == CANNED
    assert result.report is not None
    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].id == result.report.id


def test_analyze_without_project_does_not_save():
    db = Database(":memory:")
    service = CompetitiveLandscapeService(CompetitiveLandscapeReportRepository(db))
    result = service.analyze(FakeProvider(), "A cozy 2D farming sim.")
    assert result.report is None


def test_analyze_records_usage():
    db = Database(":memory:")
    service = CompetitiveLandscapeService(CompetitiveLandscapeReportRepository(db))
    recorded = []
    service.analyze(FakeProvider(), "desc", record_usage=lambda p: recorded.append(p))
    assert recorded == ["fake"]
