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

from PySide6.QtWidgets import QApplication, QFrame  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.screens.settings import SettingsScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


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
