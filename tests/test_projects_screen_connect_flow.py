"""ProjectsScreen's connect-a-project flow: folder-first project creation,
the actionable engine-mismatch prompt, and the Godot/Unreal executable
auto-discovery suggestion.

Connect-a-Project Setup Simplification spec, Finding 1 fix 2/3 and Finding 2
fix 1/2 (regression coverage, fix 4). First dedicated test coverage for
``ProjectsScreen`` -- there was none before this (see
``tests/test_projects.py``, which only exercises the service/repository
layer). No display is available in this environment, so this uses Qt's
offscreen platform plugin, matching the pattern used by the other screen
tests (e.g. ``tests/test_godot_unreal_ui_dispatch.py``).
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.screens.projects import ProjectsScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def _make_godot_project(root) -> None:
    root.mkdir()
    (root / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="Fixture Game"\n',
        encoding="utf-8",
    )


def _make_unreal_project(root, association: str = "5.3") -> None:
    root.mkdir()
    (root / "FixtureGame.uproject").write_text(
        json.dumps({"FileVersion": 3, "EngineAssociation": association}), encoding="utf-8"
    )


def _make_unity_project(root) -> None:
    root.mkdir()
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()


# --- Finding 1 fix 2: folder first, engine confirmed after -------------------


def test_first_click_with_a_folder_detects_engine_and_waits_for_confirmation(
    tmp_path, monkeypatch
):
    services = _services(tmp_path)
    screen = ProjectsScreen(services)
    godot_folder = tmp_path / "fixture-godot"
    _make_godot_project(godot_folder)
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(godot_folder),
    )

    screen._name_input.setText("Moonlit Depths")
    screen._create()

    # No project created yet -- waiting on a second click.
    assert services.projects.list_projects() == []
    assert screen._pending_new_project_folder == str(godot_folder)
    assert screen._engine_input.currentText() == "Godot"
    assert "Godot" in screen._new_project_status.text()
    assert "Fixture Game" in screen._new_project_status.text()


def test_second_click_creates_the_project_with_the_detected_engine_and_attaches_folder(
    tmp_path, monkeypatch
):
    services = _services(tmp_path)
    screen = ProjectsScreen(services)
    godot_folder = tmp_path / "fixture-godot"
    _make_godot_project(godot_folder)
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(godot_folder),
    )

    screen._name_input.setText("Moonlit Depths")
    screen._create()  # picks the folder, detects Godot, waits
    screen._create()  # confirms

    projects = services.projects.list_projects()
    assert len(projects) == 1
    project = projects[0]
    assert project.engine == "Godot"
    assert project.path == str(godot_folder)
    assert project.validation_status == "valid"
    assert screen._pending_new_project_folder is None  # state reset


def test_user_can_override_the_detected_engine_before_the_second_click(tmp_path, monkeypatch):
    services = _services(tmp_path)
    screen = ProjectsScreen(services)
    godot_folder = tmp_path / "fixture-godot"
    _make_godot_project(godot_folder)
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(godot_folder),
    )

    # Overriding to "Other" means the folder will fail Unity-shaped
    # validation against this real Godot folder, which would otherwise
    # trigger the engine-mismatch switch prompt (Finding 1 fix 3, tested
    # separately below) -- decline it here so this test stays focused on
    # just "the override is respected", not that separate behavior.
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr("spiced.ui.screens.projects.QMessageBox.warning", lambda *a, **k: None)

    screen._name_input.setText("Moonlit Depths")
    screen._create()  # detects Godot, pre-selects the combo
    assert screen._engine_input.currentText() == "Godot"

    # The combo box is still a real, editable escape hatch -- override it
    # before confirming.
    screen._engine_input.setCurrentText("Other")
    screen._create()

    project = services.projects.list_projects()[0]
    assert project.engine == "Other"


def test_canceling_the_folder_dialog_creates_a_shell_project_immediately(tmp_path, monkeypatch):
    # Old behavior, preserved: no folder handy yet is still a supported path.
    services = _services(tmp_path)
    screen = ProjectsScreen(services)
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QFileDialog.getExistingDirectory", lambda *a, **k: ""
    )

    screen._name_input.setText("No Folder Yet")
    screen._engine_input.setCurrentText("Unreal")
    screen._create()

    projects = services.projects.list_projects()
    assert len(projects) == 1
    assert projects[0].engine == "Unreal"
    assert projects[0].path is None
    assert screen._pending_new_project_folder is None


def test_unrecognized_folder_falls_back_to_unity_with_an_explanatory_status(tmp_path, monkeypatch):
    services = _services(tmp_path)
    screen = ProjectsScreen(services)
    empty_folder = tmp_path / "not-a-game-project"
    empty_folder.mkdir()
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(empty_folder),
    )

    screen._name_input.setText("Mystery Project")
    screen._create()

    assert screen._engine_input.currentText() == "Unity"
    assert "Couldn't tell" in screen._new_project_status.text()


# --- Finding 1 fix 3: actionable mismatch warning -----------------------------


def test_choose_folder_mismatch_offers_a_switch_and_switches_on_yes(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths", engine="Unity")
    services.set_active_project(project.id)
    screen = ProjectsScreen(services)

    godot_folder = tmp_path / "fixture-godot"
    _make_godot_project(godot_folder)
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(godot_folder),
    )
    prompts = []
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QMessageBox.question",
        lambda *a, **k: prompts.append(a[2]) or QMessageBox.StandardButton.Yes,
    )

    screen._choose_folder()

    assert len(prompts) == 1
    assert "Godot" in prompts[0]
    updated = services.projects.get_project(project.id)
    assert updated.engine == "Godot"
    assert updated.validation_status == "valid"


def test_choose_folder_mismatch_declining_the_switch_keeps_the_original_engine(
    tmp_path, monkeypatch
):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths", engine="Unity")
    services.set_active_project(project.id)
    screen = ProjectsScreen(services)

    godot_folder = tmp_path / "fixture-godot"
    _make_godot_project(godot_folder)
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(godot_folder),
    )
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.No,
    )
    warnings = []
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QMessageBox.warning",
        lambda *a, **k: warnings.append(True),
    )

    screen._choose_folder()

    assert warnings == [True]
    assert services.projects.get_project(project.id).engine == "Unity"


def test_choose_folder_with_no_alternate_engine_shows_a_plain_warning_not_a_prompt(
    tmp_path, monkeypatch
):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths", engine="Unity")
    services.set_active_project(project.id)
    screen = ProjectsScreen(services)

    empty_folder = tmp_path / "not-a-project"
    empty_folder.mkdir()
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(empty_folder),
    )
    questions = []
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QMessageBox.question",
        lambda *a, **k: questions.append(True) or QMessageBox.StandardButton.No,
    )
    warnings = []
    monkeypatch.setattr(
        "spiced.ui.screens.projects.QMessageBox.warning",
        lambda *a, **k: warnings.append(True),
    )

    screen._choose_folder()

    assert questions == []  # detect_engine() also says Unity -- nothing to offer
    assert warnings == [True]


# --- Finding 2: Godot/Unreal executable auto-discovery ----------------------


def test_unreal_suggest_button_appears_when_launcher_manifest_matches(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Fixture Game", engine="Unreal")
    unreal_folder = tmp_path / "fixture-unreal"
    _make_unreal_project(unreal_folder, association="5.3")
    services.projects.attach_engine_folder(project.id, str(unreal_folder))
    services.set_active_project(project.id)

    monkeypatch.setattr(
        "spiced.ui.screens.projects.find_installed_unreal_engines",
        lambda: {"5.3": r"C:\Program Files\Epic Games\UE_5.3"},
    )
    screen = ProjectsScreen(services)
    screen._update_detail()

    assert screen._engine_suggest_btn.isHidden() is False
    assert "5.3" in screen._engine_suggest_btn.text()

    screen._on_use_suggested_engine_path()

    updated = services.projects.get_project(project.id)
    assert updated.unity_editor_path_override == r"C:\Program Files\Epic Games\UE_5.3"


def test_unreal_suggest_button_hidden_when_no_manifest_match(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Fixture Game", engine="Unreal")
    unreal_folder = tmp_path / "fixture-unreal"
    _make_unreal_project(unreal_folder, association="5.3")
    services.projects.attach_engine_folder(project.id, str(unreal_folder))
    services.set_active_project(project.id)

    monkeypatch.setattr(
        "spiced.ui.screens.projects.find_installed_unreal_engines", lambda: {}
    )
    screen = ProjectsScreen(services)
    screen._update_detail()

    assert screen._engine_suggest_btn.isHidden() is True


def test_godot_suggest_button_appears_when_found_on_path(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Fixture Game", engine="Godot")
    services.set_active_project(project.id)

    monkeypatch.setattr(
        "spiced.ui.screens.projects.find_godot_on_path", lambda: r"C:\Godot\godot.exe"
    )
    screen = ProjectsScreen(services)
    screen._update_detail()

    assert screen._engine_suggest_btn.isHidden() is False
    assert r"C:\Godot\godot.exe" in screen._engine_suggest_btn.text()

    screen._on_use_suggested_engine_path()

    updated = services.projects.get_project(project.id)
    assert updated.unity_editor_path_override == r"C:\Godot\godot.exe"


def test_suggest_button_hidden_once_an_override_is_already_set(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Fixture Game", engine="Godot")
    services.projects.set_unity_test_run_settings(project.id, False, r"C:\Already\godot.exe")
    services.set_active_project(project.id)

    monkeypatch.setattr(
        "spiced.ui.screens.projects.find_godot_on_path", lambda: r"C:\Godot\godot.exe"
    )
    screen = ProjectsScreen(services)
    screen._update_detail()

    # An override already exists -- this is a one-time suggestion, not a
    # standing nag.
    assert screen._engine_suggest_btn.isHidden() is True


def test_suggest_button_hidden_for_unity_projects(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Fixture Game", engine="Unity")
    services.set_active_project(project.id)
    screen = ProjectsScreen(services)
    screen._update_detail()

    assert screen._engine_suggest_btn.isHidden() is True
