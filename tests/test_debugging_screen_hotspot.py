"""DebuggingScreen's repeat-offender ("hotspot") line above Recent sessions.

Unity Alpha Readiness Spec, Priority 3c: a quiet, non-blocking line naming
a script that's shown up across several different past analyses -- shown
once per project per app session, not recomputed on every refresh().

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching every other screen test.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.storage.debug_sessions import DebugSessionRepository  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def _seed_sessions(services: Services, project_id: int, detected_file: str, count: int) -> None:
    sessions = DebugSessionRepository(services.db)
    for _ in range(count):
        sessions.create(
            project_id=project_id,
            source_type="paste",
            summary="summary",
            detected_error_type="NullReferenceException",
            detected_file=detected_file,
        )


def test_hotspot_label_hidden_with_no_sessions(tmp_path):
    from spiced.ui.screens.debugging import DebuggingScreen

    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)

    screen = DebuggingScreen(services)

    assert screen._hotspot_label.isHidden() is True
    services.close()


def test_hotspot_label_shows_the_repeat_offending_script(tmp_path):
    from spiced.ui.screens.debugging import DebuggingScreen

    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    _seed_sessions(services, project.id, "HealthPickup.cs", 4)

    screen = DebuggingScreen(services)

    assert screen._hotspot_label.isHidden() is False
    assert "HealthPickup.cs" in screen._hotspot_label.text()
    assert "4" in screen._hotspot_label.text()
    services.close()


def test_hotspot_computed_once_per_project_per_session(tmp_path):
    """Repeated refresh() calls for the same project shouldn't recompute or
    re-trigger the hotspot check -- only the first one should."""
    from spiced.ui.screens.debugging import DebuggingScreen

    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    _seed_sessions(services, project.id, "HealthPickup.cs", 4)

    screen = DebuggingScreen(services)
    assert screen._hotspot_shown_for_project_id == project.id

    calls = []
    real_hotspots = services.debugging.hotspots
    services.debugging.hotspots = lambda *a, **k: calls.append(1) or real_hotspots(*a, **k)

    screen.refresh()
    screen.refresh()

    assert calls == []  # never recomputed for the same project
    services.close()


def test_hotspot_recomputes_after_switching_projects(tmp_path):
    from spiced.ui.screens.debugging import DebuggingScreen

    services = _services(tmp_path)
    project_a = services.projects.create_project("Moonlit Depths")
    project_b = services.projects.create_project("Fixture Game")
    services.set_active_project(project_a.id)
    _seed_sessions(services, project_a.id, "HealthPickup.cs", 4)
    _seed_sessions(services, project_b.id, "Enemy.cs", 5)

    screen = DebuggingScreen(services)
    assert "HealthPickup.cs" in screen._hotspot_label.text()

    services.set_active_project(project_b.id)
    screen.refresh()

    assert "Enemy.cs" in screen._hotspot_label.text()
    services.close()
