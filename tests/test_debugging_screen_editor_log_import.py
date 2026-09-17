"""DebuggingScreen's one-click "Import latest Editor.log" button.

Unity Alpha Readiness Spec, Priority 3a: Unity writes Editor.log to a
fixed, well-known OS path (core.engine_executable_resolve.
find_unity_editor_log) -- this button reads it the same way
``_import_file`` reads a manually-picked file, just from a pre-resolved
source instead of a file dialog.

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching every other screen test.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.core.engine_dispatch import ENGINE_GODOT, ENGINE_UNITY  # noqa: E402
from spiced.ui.screens import debugging as debugging_module  # noqa: E402
from spiced.ui.screens.debugging import DebuggingScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def test_editor_log_button_disabled_with_no_active_project(tmp_path, monkeypatch):
    monkeypatch.setattr(
        debugging_module, "find_unity_editor_log", lambda: tmp_path / "Editor.log"
    )
    screen = DebuggingScreen(_services(tmp_path))

    assert screen._editor_log_btn.isEnabled() is False


def test_editor_log_button_disabled_when_log_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(debugging_module, "find_unity_editor_log", lambda: None)
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths", engine=ENGINE_UNITY)
    services.set_active_project(project.id)

    screen = DebuggingScreen(services)

    assert screen._editor_log_btn.isEnabled() is False
    services.close()


def test_editor_log_button_disabled_for_non_unity_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(
        debugging_module, "find_unity_editor_log", lambda: tmp_path / "Editor.log"
    )
    services = _services(tmp_path)
    project = services.projects.create_project("Fixture Game", engine=ENGINE_GODOT)
    services.set_active_project(project.id)

    screen = DebuggingScreen(services)

    assert screen._editor_log_btn.isEnabled() is False
    services.close()


def test_editor_log_button_enabled_for_unity_project_with_a_log(tmp_path, monkeypatch):
    log_path = tmp_path / "Editor.log"
    log_path.write_text("Unity console output", encoding="utf-8")
    monkeypatch.setattr(debugging_module, "find_unity_editor_log", lambda: log_path)
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths", engine=ENGINE_UNITY)
    services.set_active_project(project.id)

    screen = DebuggingScreen(services)

    assert screen._editor_log_btn.isEnabled() is True
    services.close()


def test_clicking_import_editor_log_populates_the_log_input(tmp_path, monkeypatch):
    log_path = tmp_path / "Editor.log"
    log_path.write_text("NullReferenceException at Foo.cs:12", encoding="utf-8")
    monkeypatch.setattr(debugging_module, "find_unity_editor_log", lambda: log_path)
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths", engine=ENGINE_UNITY)
    services.set_active_project(project.id)

    screen = DebuggingScreen(services)
    screen._import_editor_log()

    assert screen._log_input.toPlainText() == "NullReferenceException at Foo.cs:12"
    assert screen._pending_filename == "Editor.log"
    services.close()


def test_import_editor_log_shows_a_message_when_none_found(tmp_path, monkeypatch):
    monkeypatch.setattr(debugging_module, "find_unity_editor_log", lambda: None)
    shown = []
    monkeypatch.setattr(
        "spiced.ui.screens.debugging.QMessageBox.information",
        lambda *a, **k: shown.append(True),
    )
    screen = DebuggingScreen(_services(tmp_path))

    screen._import_editor_log()

    assert shown == [True]
    assert screen._log_input.toPlainText() == ""
