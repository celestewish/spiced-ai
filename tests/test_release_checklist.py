import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import RELEASE_CHECKLIST_RULES, build_release_checklist_prompt
from spiced.core.release_checklist import (
    ITCH,
    LARGE_BUILD_HEADS_UP_BYTES,
    STEAM,
    analyze_checklist,
    build_checklist,
)


class FakeProvider(AIProvider):
    name = "fake"

    def is_available(self):
        return True

    def generate(self, prompt):
        return AIResponse(text="Worth prioritizing first:\n- Item.", provider=self.name)


def test_build_checklist_rejects_unknown_platform():
    with pytest.raises(ValueError):
        build_checklist("epic")


def test_steam_checklist_has_items_and_verify_note():
    checklist = build_checklist(STEAM)
    assert checklist.platform_label == "Steam"
    assert len(checklist.items) > 0
    assert "Steam" in checklist.verify_note
    assert "verify" in checklist.verify_note.lower()


def test_itch_checklist_has_items_and_verify_note():
    checklist = build_checklist(ITCH)
    assert checklist.platform_label == "itch.io"
    assert len(checklist.items) > 0
    assert any("no hard build-size limit" in item.text for item in checklist.items)


def test_checklists_are_deterministic():
    assert build_checklist(STEAM) == build_checklist(STEAM)


def test_large_build_size_adds_a_heads_up_item():
    small = build_checklist(STEAM, build_size_bytes=100)
    large = build_checklist(STEAM, build_size_bytes=LARGE_BUILD_HEADS_UP_BYTES + 1)
    assert not any("GB" in item.text for item in small.items)
    assert any("GB" in item.text for item in large.items)


def test_build_size_below_threshold_does_not_add_heads_up():
    checklist = build_checklist(STEAM, build_size_bytes=LARGE_BUILD_HEADS_UP_BYTES - 1)
    assert not any("GB" in item.text for item in checklist.items)


def test_analyze_checklist_calls_provider_and_returns_text():
    checklist = build_checklist(ITCH)
    text = analyze_checklist(FakeProvider(), checklist, project_name="Moonlit Depths")
    assert text == "Worth prioritizing first:\n- Item."


def test_release_checklist_prompt_includes_rules_and_items():
    checklist = build_checklist(STEAM)
    prompt = build_release_checklist_prompt(checklist, project_name="Moonlit Depths")
    for rule in RELEASE_CHECKLIST_RULES:
        assert rule in prompt
    assert checklist.items[0].text in prompt
    assert "Moonlit Depths" in prompt
