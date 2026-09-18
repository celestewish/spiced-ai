"""core.api_key_store: local fallback storage for AI provider API keys.

Connect-a-Project Setup Simplification spec, Finding 3 fix 4. The
get_bundled_api_key coverage below is Pre-Alpha Testing spec: a
maintainer-supplied default key baked into a packaged build.
"""

from __future__ import annotations

import sys

import pytest

from spiced.core import api_key_store
from spiced.core.api_key_store import get_api_key, get_bundled_api_key, set_api_key


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


# --- get_bundled_api_key (Pre-Alpha Testing spec) ----------------------------


def test_bundled_key_missing_returns_none_not_frozen(tmp_path, monkeypatch):
    # Not frozen -> reads from <repo root>/packaging/vendor/, derived from
    # the module's own __file__ three parents up (src/spiced/core/ -> root).
    fake_module_file = tmp_path / "fakerepo" / "src" / "spiced" / "core" / "api_key_store.py"
    monkeypatch.setattr(api_key_store, "__file__", str(fake_module_file))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert get_bundled_api_key("openai") is None


def test_bundled_key_read_from_repo_relative_vendor_dir_when_not_frozen(tmp_path, monkeypatch):
    repo_root = tmp_path / "fakerepo"
    fake_module_file = repo_root / "src" / "spiced" / "core" / "api_key_store.py"
    monkeypatch.setattr(api_key_store, "__file__", str(fake_module_file))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    vendor = repo_root / "packaging" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "bundled_openai_key.txt").write_text("  sk-bundled-openai  \n", encoding="utf-8")

    assert get_bundled_api_key("openai") == "sk-bundled-openai"
    assert get_bundled_api_key("gemini") is None  # scoped per provider, same as get_api_key


def test_bundled_key_read_next_to_executable_when_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Spiced.exe"))
    (tmp_path / "bundled_gemini_key.txt").write_text("sk-bundled-gemini", encoding="utf-8")

    assert get_bundled_api_key("gemini") == "sk-bundled-gemini"


def test_bundled_key_blank_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Spiced.exe"))
    (tmp_path / "bundled_openai_key.txt").write_text("   \n", encoding="utf-8")

    assert get_bundled_api_key("openai") is None
