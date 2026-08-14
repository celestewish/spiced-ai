"""DebuggingScreen's "Regenerate docs" button: water-fill loading wiring
(Frutiger Aero pass 5/5).

The button click handler already existed (Auto-Generated Dev Docs, Phase F);
this only covers the three call sites this PR added --
set_loading(True)/(False) around the real worker-thread launch and its
done/failed outcomes -- not the dev-docs generation logic itself, which has
its own coverage in test_dev_docs_service.py.

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching the pattern used by the other screen tests.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.screens.debugging import DebuggingScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def _fake_result() -> SimpleNamespace:
    return SimpleNamespace(
        scan=SimpleNamespace(file_count=3, class_count=2, method_count=7),
        response_text="Looks tidy.",
    )


def test_dev_docs_button_has_water_fill_enabled(tmp_path):
    screen = DebuggingScreen(_services(tmp_path))
    assert screen._dev_docs_btn._water_fill_enabled is True


def test_generate_starts_loading_immediately_for_a_selected_project(tmp_path):
    services = _services(tmp_path)
    services.set_provider_name("mock")  # never hit a real AI provider
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)

    screen = DebuggingScreen(services)
    try:
        screen._on_dev_docs_generate()

        # thread.start() is non-blocking -- these are the click handler's
        # own synchronous side effects, set before the worker thread (which
        # will shortly fail fast with "no Unity folder connected", since
        # this project has none) ever runs.
        assert screen._dev_docs_btn._loading is True
        assert screen._dev_docs_btn.isEnabled() is False
    finally:
        # Let the real (fast, offline, no-unity-folder) worker finish
        # rather than leaving a QThread running past the test.
        deadline = 0
        while screen._active_threads and deadline < 200:
            QApplication.processEvents()
            deadline += 1
        services.close()


def test_done_clears_the_loading_state(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = DebuggingScreen(services)
    screen._dev_docs_btn.set_loading(True)
    screen._dev_docs_btn.setEnabled(False)

    screen._on_dev_docs_done(_fake_result())

    assert screen._dev_docs_btn._loading is False
    assert screen._dev_docs_btn.isEnabled() is True
    services.close()


def test_failed_clears_the_loading_state(tmp_path):
    services = _services(tmp_path)
    screen = DebuggingScreen(services)
    screen._dev_docs_btn.set_loading(True)
    screen._dev_docs_btn.setEnabled(False)

    screen._on_dev_docs_failed("Connect a Unity folder for this project first.")

    assert screen._dev_docs_btn._loading is False
    assert screen._dev_docs_btn.isEnabled() is True
    services.close()
