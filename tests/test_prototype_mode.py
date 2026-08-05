"""Rapid Prototyping Mode: settings toggle round-trip plus its effect on the
Testing screen's Quick Smoke Test panel / full QA suite visibility.

No display is available in this environment, so this uses Qt's offscreen
platform plugin (same approach as test_testing_screen_build_worker.py) to
construct the real TestingScreen headlessly and inspect widget visibility —
full interactive/visual behavior can't be tested without a display, but
construction plus the widget-visibility contract can be.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.screens.testing import TestingScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


# --- Settings round-trip -----------------------------------------------------


def test_prototype_mode_disabled_by_default(tmp_path):
    services = _services(tmp_path)
    assert services.prototype_mode_enabled() is False


def test_prototype_mode_toggle_round_trips(tmp_path):
    services = _services(tmp_path)
    services.set_prototype_mode_enabled(True)
    assert services.prototype_mode_enabled() is True
    services.set_prototype_mode_enabled(False)
    assert services.prototype_mode_enabled() is False


# --- Effect on the Testing screen -------------------------------------------


def test_testing_screen_hides_smoke_test_panel_when_mode_off(tmp_path):
    # A widget never shown on screen (headless, no top-level .show()) is
    # never "visible" per Qt's ancestor-chain isVisible() -- isHidden()
    # instead reflects the explicit setVisible() flag this code actually
    # sets, regardless of whether the window itself was ever shown.
    services = _services(tmp_path)
    screen = TestingScreen(services)
    assert services.prototype_mode_enabled() is False
    assert screen._smoke_test_panel.isHidden() is True
    assert screen._qa_toggle_btn.isHidden() is True
    # The full suite is never hidden when the mode is off.
    assert screen._tabs.isHidden() is False


def test_testing_screen_shows_smoke_test_panel_when_mode_on(tmp_path):
    services = _services(tmp_path)
    services.set_prototype_mode_enabled(True)
    screen = TestingScreen(services)
    assert screen._smoke_test_panel.isHidden() is False
    assert screen._qa_toggle_btn.isHidden() is False
    # Collapsed (de-emphasized) by default, not hidden/removed -- still
    # reachable via the toggle button.
    assert screen._tabs.isHidden() is True


def test_testing_screen_qa_suite_toggle_expands_and_collapses(tmp_path):
    services = _services(tmp_path)
    services.set_prototype_mode_enabled(True)
    screen = TestingScreen(services)
    assert screen._tabs.isHidden() is True

    screen._on_toggle_qa_suite()
    assert screen._tabs.isHidden() is False
    # Nothing about the full suite's own tabs/content changes -- still all
    # five tabs present.
    assert screen._tabs.count() == 5  # Functional/Performance/Accessibility/Build & Release/Economy

    screen._on_toggle_qa_suite()
    assert screen._tabs.isHidden() is True


def test_smoke_test_records_a_pass_and_fail_as_test_cases(tmp_path):
    services = _services(tmp_path)
    services.set_prototype_mode_enabled(True)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = TestingScreen(services)

    screen._smoke_input.setText("Player can jump")
    screen._on_smoke_result(True)
    screen._smoke_input.setText("Player can double jump")
    screen._on_smoke_result(False)

    cases = services.testing.list_cases(project.id)
    assert len(cases) == 2
    statuses = {c.title: c.status for c in cases}
    assert statuses["Player can jump"] == "Pass"
    assert statuses["Player can double jump"] == "Fail"


def test_refresh_toggles_prototype_mode_widgets_live(tmp_path):
    services = _services(tmp_path)
    screen = TestingScreen(services)
    assert screen._smoke_test_panel.isHidden() is True

    services.set_prototype_mode_enabled(True)
    screen.refresh()
    assert screen._smoke_test_panel.isHidden() is False

    services.set_prototype_mode_enabled(False)
    screen.refresh()
    assert screen._smoke_test_panel.isHidden() is True
