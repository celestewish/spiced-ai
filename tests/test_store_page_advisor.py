"""Tests for core.store_page_advisor: prompt building + review orchestration."""

from __future__ import annotations

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import build_store_page_prompt
from spiced.core.store_page_advisor import (
    ProviderNotReadyError,
    StorePageAdvisorService,
    parse_tags,
)
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.store_page_reviews import StorePageReviewRepository

CANNED = "Here's a read on your store page draft (suggestions only, not a guarantee of anything)."


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


def test_parse_tags_splits_commas_and_newlines():
    assert parse_tags("Roguelike, Pixel Art,\nCo-op") == ["Roguelike", "Pixel Art", "Co-op"]


def test_parse_tags_handles_empty_input():
    assert parse_tags("") == []
    assert parse_tags("  ,  ,, ") == []


def test_build_store_page_prompt_includes_never_a_guarantee_language():
    prompt = build_store_page_prompt(
        title="Moonlit Depths", description="A cozy roguelike.", tags=["Roguelike", "Cozy"]
    )
    assert "Moonlit Depths" in prompt
    assert "A cozy roguelike." in prompt
    assert "Roguelike, Cozy" in prompt
    assert "never a guarantee" in prompt.lower()


def test_build_store_page_prompt_handles_missing_fields():
    prompt = build_store_page_prompt(title="", description="", tags=[])
    assert "(no title provided)" in prompt
    assert "(no description provided)" in prompt
    assert "(no tags provided)" in prompt


def test_review_raises_when_provider_not_ready():
    db = Database(":memory:")
    service = StorePageAdvisorService(StorePageReviewRepository(db))
    with pytest.raises(ProviderNotReadyError):
        service.review(FakeProvider(available=False), "Title", "Description", "tag1, tag2")


def test_review_saves_report_when_project_given():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = StorePageAdvisorService(StorePageReviewRepository(db))

    result = service.review(
        FakeProvider(), "Moonlit Depths", "A cozy roguelike.", "Roguelike, Cozy", project=project
    )

    assert result.response_text == CANNED
    assert result.review is not None
    assert result.review.title == "Moonlit Depths"
    assert result.review.tags == ["Roguelike", "Cozy"]

    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].id == result.review.id


def test_review_without_project_does_not_save():
    db = Database(":memory:")
    service = StorePageAdvisorService(StorePageReviewRepository(db))
    result = service.review(FakeProvider(), "Title", "Description", "")
    assert result.review is None


def test_review_records_usage():
    db = Database(":memory:")
    service = StorePageAdvisorService(StorePageReviewRepository(db))
    recorded = []
    service.review(
        FakeProvider(), "Title", "Description", "", record_usage=lambda p: recorded.append(p)
    )
    assert recorded == ["fake"]
