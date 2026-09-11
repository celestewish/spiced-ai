"""core.api_key_store: local fallback storage for AI provider API keys.

Connect-a-Project Setup Simplification spec, Finding 3 fix 4.
"""

from __future__ import annotations

import pytest

from spiced.core import api_key_store
from spiced.core.api_key_store import get_api_key, set_api_key


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    # Same isolation approach test_database.py-style tests would use for
    # ~/.spiced -- redirect Path.home() so this never touches the real
    # user's key store.
    monkeypatch.setattr(api_key_store.Path, "home", lambda: tmp_path)
    return tmp_path


def test_missing_store_returns_none():
    assert get_api_key("openai") is None


def test_set_then_get_round_trips():
    set_api_key("openai", "sk-test-123")
    assert get_api_key("openai") == "sk-test-123"


def test_get_is_scoped_per_provider():
    set_api_key("openai", "sk-openai")
    set_api_key("gemini", "sk-gemini")
    assert get_api_key("openai") == "sk-openai"
    assert get_api_key("gemini") == "sk-gemini"


def test_set_strips_whitespace():
    set_api_key("openai", "  sk-test-123  ")
    assert get_api_key("openai") == "sk-test-123"


def test_set_blank_clears_existing_key():
    set_api_key("openai", "sk-test-123")
    set_api_key("openai", "   ")
    assert get_api_key("openai") is None


def test_malformed_store_degrades_to_none(tmp_path):
    store = tmp_path / ".spiced" / "api_keys.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("not valid json{{{", encoding="utf-8")
    assert get_api_key("openai") is None


def test_store_not_a_dict_degrades_to_none(tmp_path):
    store = tmp_path / ".spiced" / "api_keys.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("[1, 2, 3]", encoding="utf-8")
    assert get_api_key("openai") is None


def test_set_api_key_never_raises_on_malformed_existing_store(tmp_path):
    store = tmp_path / ".spiced" / "api_keys.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("not valid json{{{", encoding="utf-8")
    set_api_key("openai", "sk-test-123")
    assert get_api_key("openai") == "sk-test-123"
