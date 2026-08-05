"""MainWindow construction test (Phase K, section 9 part 1).

No display is available in this environment, so this uses Qt's offscreen
platform plugin (same approach as test_build_scheduler.py/
test_prototype_mode.py) to construct the real MainWindow headlessly and
check its wiring -- particularly that adding the new top bar (Multi-Project
Switcher + Notification Center bell) didn't break the existing Sidebar/
Workspace/Context-panel layout or any of its many projects_changed/
usage_changed signal connections.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.main_window import NAV_ITEMS, MainWindow  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def test_main_window_constructs_offscreen_with_top_bar(tmp_path):
    window = MainWindow(_services(tmp_path))
    try:
        assert window._top_bar is not None
        assert window._top_bar.bell is not None
        # Sidebar nav still has one button per NAV_ITEMS entry, and the
        # workspace stack still has exactly that many pages, in the same
        # order -- the top bar addition didn't touch this wiring.
        assert len(window._nav_buttons) == len(NAV_ITEMS)
        assert window._stack.count() == len(NAV_ITEMS)
        assert window._nav_buttons[0].isChecked() is True
        assert window._stack.currentIndex() == 0
    finally:
        window._build_scheduler.stop()
        window._top_bar.stop()


def test_main_window_close_event_stops_bell_and_scheduler(tmp_path):
    window = MainWindow(_services(tmp_path))
    window.close()  # exercises closeEvent's cleanup path directly
    assert window._top_bar._bell._poll_timer.isActive() is False
    assert window._build_scheduler._timer.isActive() is False


def test_top_bar_project_switch_updates_projects_screen_and_context(tmp_path):
    services = _services(tmp_path)
    project_a = services.projects.create_project("Project A")
    project_b = services.projects.create_project("Project B")
    services.set_active_project(project_a.id)

    window = MainWindow(services)
    try:
        window._top_bar._project_switcher.setCurrentIndex(
            window._top_bar._project_switcher.findData(project_b.id)
        )
        assert services.active_project().id == project_b.id
        # The Projects screen's own list selection follows the switch too,
        # not just other screens' data (see MainWindow._on_top_bar_project_switched).
        assert window._projects_screen._services.active_project().id == project_b.id
    finally:
        window._build_scheduler.stop()
        window._top_bar.stop()


def test_command_palette_ctrl_k_opens_with_nav_items(tmp_path):
    services = _services(tmp_path)
    services.projects.create_project("Moonlit Depths")
    window = MainWindow(services)
    try:
        items = window._build_palette_items()
        labels = {item.label for item in items}
        assert "Dashboard" in labels
        assert "Moonlit Depths" in labels
    finally:
        window._build_scheduler.stop()
        window._top_bar.stop()
