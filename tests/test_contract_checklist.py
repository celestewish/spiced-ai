"""Tests for core.contract_checklist: prompt building, excerpt capping, storage discipline."""

from __future__ import annotations

import hashlib

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import CONTRACT_CHECKLIST_RULES, build_contract_checklist_prompt
from spiced.core.contract_checklist import (
    PREVIEW_EXCERPT_CHARS,
    PROMPT_EXCERPT_CHARS,
    ContractChecklistService,
    ProviderNotReadyError,
)
from spiced.storage.contract_checklist_reviews import ContractChecklistReviewRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

CANNED = "Not legal advice — this is a non-lawyer's read to help you know what to ask about."


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


def test_prompt_includes_not_legal_advice_language_repeatedly():
    prompt = build_contract_checklist_prompt("This agreement...", project_name="Moonlit Depths")
    for rule in CONTRACT_CHECKLIST_RULES:
        assert rule in prompt
    assert prompt.lower().count("not legal advice") + prompt.lower().count(
        "not a lawyer"
    ) >= 2
    assert "real lawyer" in prompt.lower()


def test_prompt_handles_empty_excerpt():
    prompt = build_contract_checklist_prompt("   ", project_name=None)
    assert "(empty" in prompt


def test_review_raises_when_provider_not_ready():
    db = Database(":memory:")
    service = ContractChecklistService(ContractChecklistReviewRepository(db))
    with pytest.raises(ProviderNotReadyError):
        service.review(FakeProvider(available=False), "some contract text")


def test_review_caps_prompt_excerpt():
    db = Database(":memory:")
    service = ContractChecklistService(ContractChecklistReviewRepository(db))
    long_text = "x " * (PROMPT_EXCERPT_CHARS)  # far longer than the cap once stripped
    result = service.review(FakeProvider(), long_text)
    assert result.response_text == CANNED


def test_review_stores_only_short_preview_and_hash_not_full_text():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = ContractChecklistService(ContractChecklistReviewRepository(db))

    long_text = "CONFIDENTIAL AGREEMENT. " * 500  # much longer than any stored preview
    result = service.review(FakeProvider(), long_text, project=project)

    assert result.review is not None
    assert result.review.excerpt_preview is not None
    assert len(result.review.excerpt_preview) <= PREVIEW_EXCERPT_CHARS
    assert len(result.review.excerpt_preview) < len(long_text)

    expected_excerpt = long_text.strip()[:PROMPT_EXCERPT_CHARS]
    expected_hash = hashlib.sha256(expected_excerpt.encode("utf-8")).hexdigest()
    assert result.review.excerpt_hash == expected_hash
    assert result.review.ai_summary == CANNED


def test_review_without_project_does_not_save():
    db = Database(":memory:")
    service = ContractChecklistService(ContractChecklistReviewRepository(db))
    result = service.review(FakeProvider(), "some contract text")
    assert result.review is None


def test_review_records_usage():
    db = Database(":memory:")
    service = ContractChecklistService(ContractChecklistReviewRepository(db))
    recorded = []
    service.review(FakeProvider(), "text", record_usage=lambda p: recorded.append(p))
    assert recorded == ["fake"]


def test_history_returns_saved_reviews():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = ContractChecklistService(ContractChecklistReviewRepository(db))
    service.review(FakeProvider(), "text one", project=project)
    service.review(FakeProvider(), "text two", project=project, source_filename="license.txt")

    history = service.history(project.id)
    assert len(history) == 2
    assert history[0].source_filename == "license.txt"
