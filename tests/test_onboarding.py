"""First-run onboarding tests.

Two layers:

- Persistence tests run against the real Services composition root on an
  in-memory database and need no GUI.
- UI smoke tests build the real MainWindow under Qt's offscreen platform and
  assert first-run display, action routing, demo loading, and manual reopen.
  They confirm onboarding never resets the developer's data.
"""

from __future__ import annotations

import os

import pytest

from spiced.app.services import Services
from spiced.core.demo_data import DEMO_PROJECT_NAME

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _services() -> Services:
    return Services(":memory:")


# --- Persistence (no GUI) -------------------------------------------------


def test_onboarding_defaults_to_incomplete_on_fresh_database() -> None:
    svc = _services()
    assert svc.onboarding_completed() is False
    svc.close()


def test_onboarding_completion_persists() -> None:
    svc = _services()
    svc.set_onboarding_completed(True)
    assert svc.onboarding_completed() is True
    svc.close()


def test_onboarding_can_be_reset_to_incomplete() -> None:
    svc = _services()
    svc.set_onboarding_completed(True)
    svc.set_onboarding_completed(False)
    assert svc.onboarding_completed() is False
    svc.close()


# --- UI smoke (offscreen Qt) ----------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _no_dialogs(monkeypatch):
    """Stop QMessageBox from blocking the offscreen event loop."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)


def _main_window(svc):
    from spiced.ui.main_window import _ONBOARDING_INDEX, MainWindow

    return MainWindow(svc), _ONBOARDING_INDEX


def test_onboarding_shows_on_fresh_database(qapp):
    svc = _services()
    window, onboarding_index = _main_window(svc)
    assert window._stack.currentIndex() == onboarding_index
    svc.close()


def test_completed_database_opens_on_dashboard(qapp):
    from spiced.ui.main_window import _DASHBOARD_INDEX

    svc = _services()
    svc.set_onboarding_completed(True)
    window, _ = _main_window(svc)
    assert window._stack.currentIndex() == _DASHBOARD_INDEX
    svc.close()


def test_skip_marks_onboarding_completed(qapp):
    from spiced.ui.main_window import _DASHBOARD_INDEX
    from spiced.ui.screens.onboarding import ACTION_SKIP

    svc = _services()
    window, _ = _main_window(svc)
    window._onboarding_screen.action_selected.emit(ACTION_SKIP)

    assert svc.onboarding_completed() is True
    assert window._stack.currentIndex() == _DASHBOARD_INDEX
    svc.close()


def test_create_project_action_navigates_to_projects(qapp):
    from spiced.ui.main_window import _PROJECTS_INDEX
    from spiced.ui.screens.onboarding import ACTION_CREATE_PROJECT

    svc = _services()
    window, _ = _main_window(svc)
    window._onboarding_screen.action_selected.emit(ACTION_CREATE_PROJECT)

    assert window._stack.currentIndex() == _PROJECTS_INDEX
    assert svc.onboarding_completed() is True
    svc.close()


def test_configure_ai_action_navigates_to_settings(qapp):
    from spiced.ui.main_window import _SETTINGS_INDEX
    from spiced.ui.screens.onboarding import ACTION_CONFIGURE_AI

    svc = _services()
    window, _ = _main_window(svc)
    window._onboarding_screen.action_selected.emit(ACTION_CONFIGURE_AI)

    assert window._stack.currentIndex() == _SETTINGS_INDEX
    svc.close()


def test_continue_action_navigates_to_dashboard(qapp):
    from spiced.ui.main_window import _DASHBOARD_INDEX
    from spiced.ui.screens.onboarding import ACTION_DASHBOARD

    svc = _services()
    window, _ = _main_window(svc)
    window._onboarding_screen.action_selected.emit(ACTION_DASHBOARD)

    assert window._stack.currentIndex() == _DASHBOARD_INDEX
    svc.close()


def test_load_demo_action_seeds_demo_and_sets_active(qapp, monkeypatch):
    from spiced.ui.main_window import _DASHBOARD_INDEX
    from spiced.ui.screens.onboarding import ACTION_LOAD_DEMO

    _no_dialogs(monkeypatch)
    svc = _services()
    window, _ = _main_window(svc)
    window._onboarding_screen.action_selected.emit(ACTION_LOAD_DEMO)

    assert svc.demo.is_seeded()
    active = svc.active_project()
    assert active is not None and active.name == DEMO_PROJECT_NAME
    assert window._stack.currentIndex() == _DASHBOARD_INDEX
    assert svc.onboarding_completed() is True
    svc.close()


def test_load_demo_reuses_existing_demo_service(qapp, monkeypatch):
    """Onboarding must not duplicate demo data — it reuses the Phase 5A service."""
    from spiced.ui.screens.onboarding import ACTION_LOAD_DEMO

    _no_dialogs(monkeypatch)
    svc = _services()
    # Pre-seed via the demo service directly; onboarding should reuse it.
    svc.load_demo_project()
    window, _ = _main_window(svc)
    window._onboarding_screen.action_selected.emit(ACTION_LOAD_DEMO)

    demo_projects = [p for p in svc.projects.list_projects() if p.name == DEMO_PROJECT_NAME]
    assert len(demo_projects) == 1
    svc.close()


def test_reopen_from_settings_shows_onboarding_without_resetting_data(qapp):
    svc = _services()
    svc.set_onboarding_completed(True)
    real = svc.projects.create_project(name="My Real Game", engine="Unity")
    svc.set_active_project(real.id)

    window, onboarding_index = _main_window(svc)
    window._settings_screen.reopen_onboarding.emit()

    # Onboarding is visible again...
    assert window._stack.currentIndex() == onboarding_index
    # ...but completion, projects, and the active selection are untouched.
    assert svc.onboarding_completed() is True
    assert svc.active_project().id == real.id
    assert [p.name for p in svc.projects.list_projects()] == ["My Real Game"]
    svc.close()


def test_reopen_then_skip_preserves_projects(qapp):
    from spiced.ui.screens.onboarding import ACTION_SKIP

    svc = _services()
    svc.set_onboarding_completed(True)
    real = svc.projects.create_project(name="Keeper", engine="Unity")

    window, _ = _main_window(svc)
    window._settings_screen.reopen_onboarding.emit()
    window._onboarding_screen.action_selected.emit(ACTION_SKIP)

    assert svc.projects.get_project(real.id).name == "Keeper"
    assert svc.onboarding_completed() is True
    svc.close()
