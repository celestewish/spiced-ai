"""SettingsScreen: construction smoke test.

There was previously no test that actually instantiated SettingsScreen (only
an import-cleanliness check in test_team_ui_imports.py) -- unlike most other
screens, which do have a construction test. Since every screen is built
eagerly at MainWindow startup with no per-screen isolation, an exception
during SettingsScreen's own construction (e.g. a bad import, or the local
Database it depends on failing to open -- see test_database.py) would take
down the whole app before any window is shown.

No display is available in this environment, so this uses Qt's offscreen
platform plugin to construct the real screen headlessly, matching the
pattern used by the other screen tests (e.g. test_prototype_mode.py).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.core import api_key_store  # noqa: E402
from spiced.ui.screens.settings import SettingsScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_key_store(tmp_path, monkeypatch):
    # Isolate the API-key store (Connect-a-Project Setup Simplification
    # spec, Finding 3 fix 1) from whatever's saved on the machine running
    # these tests -- same reasoning as tests/test_providers.py's fixture.
    monkeypatch.setattr(api_key_store.Path, "home", lambda: tmp_path)


def test_settings_screen_constructs_without_error(tmp_path):
    services = Services(db_path=str(tmp_path / "spiced.db"))
    screen = SettingsScreen(services)
    assert screen is not None
    services.close()


def test_settings_screen_sections_are_visually_separated(tmp_path):
    # Bug 3: the many unrelated toggle sections (Team, Privacy, Discord,
    # Prototyping, Accessibility, ...) used to run directly into each other
    # with no visual break beyond a section-title label. Confirm each major
    # section is now preceded by a Hairline separator, the same reusable
    # separator style the rest of the app already uses (e.g. roadmap.py).
    services = Services(db_path=str(tmp_path / "spiced.db"))
    screen = SettingsScreen(services)

    hairlines = [w for w in screen.findChildren(QFrame) if w.objectName() == "Hairline"]
    assert len(hairlines) >= 8

    services.close()


# --- API key field (Connect-a-Project Setup Simplification spec, Finding 3
# fix 1/4) ---


def test_api_key_field_hidden_for_mock_provider(tmp_path):
    # The screen is never .show()n in this headless test (offscreen
    # platform, no top-level window) -- isVisible() would read False for
    # every widget regardless of our own setVisible() calls, since it
    # factors in ancestor visibility. isHidden() reflects only this
    # widget's own explicit hidden flag, which is what _refresh_api_key_
    # section() actually toggles.
    services = Services(db_path=str(tmp_path / "spiced.db"))
    screen = SettingsScreen(services)
    screen._provider_box.setCurrentText("mock")

    assert screen._api_key_input.isHidden() is True

    services.close()


def test_api_key_field_visible_for_openai_provider(tmp_path):
    services = Services(db_path=str(tmp_path / "spiced.db"))
    screen = SettingsScreen(services)
    screen._provider_box.setCurrentText("openai")

    assert screen._api_key_input.isHidden() is False

    services.close()


def test_saving_api_key_through_the_field_is_read_back(tmp_path):
    services = Services(db_path=str(tmp_path / "spiced.db"))
    screen = SettingsScreen(services)
    screen._provider_box.setCurrentText("openai")

    screen._api_key_input.setText("sk-typed-in")
    screen._on_save_api_key()

    assert api_key_store.get_api_key("openai") == "sk-typed-in"
    assert "saved" in screen._api_key_status.text().lower()

    services.close()


def test_env_var_still_wins_when_both_are_set(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    api_key_store.set_api_key("openai", "sk-saved")

    services = Services(db_path=str(tmp_path / "spiced.db"))
    screen = SettingsScreen(services)
    screen._provider_box.setCurrentText("openai")

    assert "environment" in screen._api_key_status.text().lower()

    services.close()


def test_no_key_configured_status_when_store_is_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    services = Services(db_path=str(tmp_path / "spiced.db"))
    screen = SettingsScreen(services)
    screen._provider_box.setCurrentText("openai")

    assert "no key configured" in screen._api_key_status.text().lower()

    services.close()


def test_bundled_key_status_shown_when_only_a_bundled_key_is_available(tmp_path, monkeypatch):
    # Pre-Alpha Testing spec: a tester with neither an env var nor a saved
    # key of their own, but a maintainer-bundled default, should see that
    # explained -- not the old "no key configured yet" text, which would be
    # actively wrong once a bundled key makes the provider actually work.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(api_key_store.sys, "frozen", True, raising=False)
    monkeypatch.setattr(api_key_store.sys, "executable", str(tmp_path / "Spiced.exe"))
    (tmp_path / "bundled_openai_key.txt").write_text("sk-bundled", encoding="utf-8")

    services = Services(db_path=str(tmp_path / "spiced.db"))
    screen = SettingsScreen(services)
    screen._provider_box.setCurrentText("openai")

    assert "built-in" in screen._api_key_status.text().lower()

    services.close()


def test_saved_key_status_wins_over_bundled_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api_key_store.set_api_key("openai", "sk-saved")
    monkeypatch.setattr(api_key_store.sys, "frozen", True, raising=False)
    monkeypatch.setattr(api_key_store.sys, "executable", str(tmp_path / "Spiced.exe"))
    (tmp_path / "bundled_openai_key.txt").write_text("sk-bundled", encoding="utf-8")

    services = Services(db_path=str(tmp_path / "spiced.db"))
    screen = SettingsScreen(services)
    screen._provider_box.setCurrentText("openai")

    assert "a key is saved" in screen._api_key_status.text().lower()

    services.close()
