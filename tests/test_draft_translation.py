"""Tests for core.draft_translation: format parsing + prompt building + orchestration."""

from __future__ import annotations

import json

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import DRAFT_TRANSLATION_RULES, build_draft_translation_prompt
from spiced.core.draft_translation import (
    FORMAT_CSV,
    FORMAT_JSON,
    FORMAT_PLAIN,
    DraftTranslationService,
    NoDialogueError,
    ProviderNotReadyError,
    parse_dialogue,
)
from spiced.storage.database import Database
from spiced.storage.draft_translations import DraftTranslationRepository
from spiced.storage.projects import ProjectRepository

CANNED = "Draft translation only — for a human translator to review and refine."


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


# --- Format parsing ----------------------------------------------------------


def test_parse_plain_text_one_line_per_entry():
    parsed = parse_dialogue("Hello, traveler.\n\nYour journey begins now.\n")
    assert parsed.source_format == FORMAT_PLAIN
    assert parsed.lines == ["Hello, traveler.", "Your journey begins now."]


def test_parse_json_flat_list_of_strings():
    parsed = parse_dialogue(json.dumps(["Hello, traveler.", "Goodbye."]))
    assert parsed.source_format == FORMAT_JSON
    assert parsed.lines == ["Hello, traveler.", "Goodbye."]


def test_parse_json_list_of_objects_keeps_ids():
    data = [{"id": "greeting", "text": "Hello, traveler."}, {"id": "farewell", "text": "Goodbye."}]
    parsed = parse_dialogue(json.dumps(data))
    assert parsed.source_format == FORMAT_JSON
    assert [e.entry_id for e in parsed.entries] == ["greeting", "farewell"]
    assert parsed.lines == ["Hello, traveler.", "Goodbye."]


def test_parse_json_flat_object_mapping():
    data = {"greeting": "Hello, traveler.", "farewell": "Goodbye."}
    parsed = parse_dialogue(json.dumps(data))
    assert parsed.source_format == FORMAT_JSON
    assert set(parsed.lines) == {"Hello, traveler.", "Goodbye."}


def test_parse_csv_with_text_column():
    parsed = parse_dialogue("id,text\ngreeting,Hello there\nfarewell,Goodbye")
    assert parsed.source_format == FORMAT_CSV
    assert parsed.lines == ["Hello there", "Goodbye"]
    assert [e.entry_id for e in parsed.entries] == ["greeting", "farewell"]


def test_parse_falls_back_to_plain_text_when_not_json_or_csv():
    parsed = parse_dialogue("Just a plain line of dialogue with no structure.")
    assert parsed.source_format == FORMAT_PLAIN
    assert parsed.lines == ["Just a plain line of dialogue with no structure."]


def test_parse_empty_text_returns_no_entries():
    parsed = parse_dialogue("   ")
    assert parsed.entries == []
    assert parsed.entry_count == 0


# --- Prompt building -----------------------------------------------------------


def test_prompt_includes_rules_numbered_lines_and_target_language():
    prompt = build_draft_translation_prompt(
        ["Hello, traveler.", "Goodbye."], target_language="Japanese", project_name="Moonlit Depths"
    )
    for rule in DRAFT_TRANSLATION_RULES:
        assert rule in prompt
    assert "1. Hello, traveler." in prompt
    assert "2. Goodbye." in prompt
    assert "Target language: Japanese" in prompt
    assert "Moonlit Depths" in prompt


def test_prompt_repeats_draft_not_ship_ready_language():
    prompt = build_draft_translation_prompt(["Hi."], target_language="French")
    assert prompt.lower().count("draft") >= 2
    assert "ship-ready" in prompt.lower() or "ship ready" in prompt.lower()


# --- Service orchestration ------------------------------------------------------


def test_translate_raises_when_provider_not_ready():
    db = Database(":memory:")
    service = DraftTranslationService(DraftTranslationRepository(db))
    with pytest.raises(ProviderNotReadyError):
        service.translate(FakeProvider(available=False), "Hello.", "French")


def test_translate_raises_when_nothing_parsed():
    db = Database(":memory:")
    service = DraftTranslationService(DraftTranslationRepository(db))
    with pytest.raises(NoDialogueError):
        service.translate(FakeProvider(), "   ", "French")


def test_translate_saves_translation_when_project_given():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = DraftTranslationService(DraftTranslationRepository(db))

    result = service.translate(
        FakeProvider(), "Hello, traveler.\nGoodbye.", "Japanese", project=project
    )

    assert result.response_text == CANNED
    assert result.translation is not None
    assert result.translation.entry_count == 2
    assert result.translation.target_language == "Japanese"
    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].id == result.translation.id


def test_translate_without_project_does_not_save():
    db = Database(":memory:")
    service = DraftTranslationService(DraftTranslationRepository(db))
    result = service.translate(FakeProvider(), "Hello.", "French")
    assert result.translation is None


def test_translate_records_usage():
    db = Database(":memory:")
    service = DraftTranslationService(DraftTranslationRepository(db))
    recorded = []
    service.translate(
        FakeProvider(), "Hello.", "French", record_usage=lambda p: recorded.append(p)
    )
    assert recorded == ["fake"]
