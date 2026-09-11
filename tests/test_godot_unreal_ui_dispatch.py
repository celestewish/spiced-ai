"""Smoke tests: the Godot/Unreal UI follow-up's engine-conditional copy and
widget state actually render correctly for a Godot/Unreal active project,
across the three screens this phase touched.

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching the pattern used by the other screen tests (see
``test_debugging_screen_dev_docs_streaming.py``). This is real widget
construction and real ``Services``/``Project`` objects -- not a mock of the
UI layer -- the closest thing to an automated version of "run the app and
look at the screen" this repo's conventions support (there is no automated
UI-interaction/screenshot testing here otherwise).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.screens.debugging import DebuggingScreen  # noqa: E402
from spiced.ui.screens.projects import ProjectsScreen  # noqa: E402
from spiced.ui.screens.testing import EDIT_MODE, PLAY_MODE, TestingScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services_with_project(tmp_path, engine: str):
    services = Services(db_path=str(tmp_path / "spiced.db"))
    project = services.projects.create_project("Fixture Game", engine=engine)
    services.set_active_project(project.id)
    return services, project


# --- Debugging Buddy: Dev Docs + Asset Health intro copy --------------------


def test_debugging_screen_dev_docs_intro_is_godot_flavored(tmp_path):
    services, _project = _services_with_project(tmp_path, "Godot")
    screen = DebuggingScreen(services)
    screen.refresh()
    text = screen._dev_docs_intro.text()
    assert ".gd scripts" in text
    assert ".cs scripts" not in text


def test_debugging_screen_dev_docs_intro_is_unreal_flavored(tmp_path):
    services, _project = _services_with_project(tmp_path, "Unreal")
    screen = DebuggingScreen(services)
    screen.refresh()
    text = screen._dev_docs_intro.text()
    assert "C++ headers" in text
    assert "Source/" in text


def test_debugging_screen_dev_docs_intro_defaults_to_unity(tmp_path):
    services, _project = _services_with_project(tmp_path, "Unity")
    screen = DebuggingScreen(services)
    screen.refresh()
    assert ".cs scripts" in screen._dev_docs_intro.text()


def test_debugging_screen_asset_health_intro_mentions_broken_scene_refs_for_godot(tmp_path):
    services, _project = _services_with_project(tmp_path, "Godot")
    screen = DebuggingScreen(services)
    screen.refresh()
    text = screen._asset_health_intro.text()
    assert "missing file" in text
    assert "no separate Assets/ folder" in text  # explains the absence, doesn't imply one exists


def test_debugging_screen_asset_health_intro_mentions_content_folder_for_unreal(tmp_path):
    services, _project = _services_with_project(tmp_path, "Unreal")
    screen = DebuggingScreen(services)
    screen.refresh()
    text = screen._asset_health_intro.text()
    assert "Content/" in text
    assert "Editor itself" in text


# --- Testing screen: Run Tests platform pills + Build Pipeline combo -------


def test_testing_screen_hides_platform_pills_for_godot(tmp_path):
    # isHidden() (the explicit hide/show flag) rather than isVisible() (which
    # also depends on the whole ancestor chain, including the screen itself,
    # actually being shown -- never true for an offscreen-constructed,
    # never-.show()'d screen like this one).
    services, _project = _services_with_project(tmp_path, "Godot")
    screen = TestingScreen(services)
    screen.refresh()
    for platform in (EDIT_MODE, PLAY_MODE):
        assert screen._unity_platform_buttons[platform].isHidden() is True


def test_testing_screen_shows_platform_pills_for_unity(tmp_path):
    services, _project = _services_with_project(tmp_path, "Unity")
    screen = TestingScreen(services)
    screen.refresh()
    for platform in (EDIT_MODE, PLAY_MODE):
        assert screen._unity_platform_buttons[platform].isHidden() is False


def test_testing_screen_run_tests_intro_is_godot_flavored(tmp_path):
    services, _project = _services_with_project(tmp_path, "Godot")
    screen = TestingScreen(services)
    screen.refresh()
    assert "GUT test suite" in screen._unity_run_intro.text()


def test_testing_screen_build_platform_combo_empty_for_godot_with_no_presets(tmp_path):
    services, project = _services_with_project(tmp_path, "Godot")
    services.projects.set_build_pipeline_settings(project.id, True, None)
    screen = TestingScreen(services)
    screen.refresh()
    assert screen._build_platform_input.count() == 0


def test_testing_screen_build_platform_combo_has_unity_targets_by_default(tmp_path):
    services, project = _services_with_project(tmp_path, "Unity")
    services.projects.set_build_pipeline_settings(project.id, True, None)
    screen = TestingScreen(services)
    screen.refresh()
    assert screen._build_platform_input.count() > 0
    assert screen._build_platform_input.itemText(0) == "StandaloneWindows64"


# --- Projects screen: opt-in accordion copy/pickers -------------------------


def test_projects_screen_editor_path_label_is_unreal_flavored(tmp_path):
    services, project = _services_with_project(tmp_path, "Unreal")
    screen = ProjectsScreen(services)
    screen._update_detail()
    assert "Engine install folder" in screen._unity_editor_path_label.text()


def test_projects_screen_editor_path_label_is_godot_flavored(tmp_path):
    services, project = _services_with_project(tmp_path, "Godot")
    screen = ProjectsScreen(services)
    screen._update_detail()
    assert "Godot executable path" in screen._unity_editor_path_label.text()


def test_projects_screen_build_pipeline_intro_mentions_uat_for_unreal(tmp_path):
    services, project = _services_with_project(tmp_path, "Unreal")
    screen = ProjectsScreen(services)
    screen._update_detail()
    assert "Automation Tool (UAT)" in screen._build_pipeline_intro.text()


def test_projects_screen_build_pipeline_intro_mentions_export_presets_for_godot(tmp_path):
    services, project = _services_with_project(tmp_path, "Godot")
    screen = ProjectsScreen(services)
    screen._update_detail()
    assert "export presets" in screen._build_pipeline_intro.text()
