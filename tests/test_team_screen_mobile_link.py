"""Tests for the Team screen's "Copy mobile link" button (Phase L,
Companion Mobile View, Stretch tier): the desktop app's only place that can
hand a developer a ready-to-open link carrying their session token as a
``?token=`` query param -- see ``ui.screens.team``'s own comment for why.

No display is available in this environment, so this uses Qt's offscreen
platform plugin (same approach as test_prototype_mode.py) to construct the
real TeamScreen headlessly and inspect clipboard/status-label state.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.screens.team import TeamScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def test_copy_mobile_link_without_active_project_shows_a_hint(tmp_path):
    screen = TeamScreen(_services(tmp_path))
    screen._on_copy_mobile_link()
    assert "team-linked project" in screen._mobile_link_status.text()


def test_copy_mobile_link_without_sign_in_shows_a_hint(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.projects.ensure_project_uuid(project.id)
    services.set_active_project(project.id)
    screen = TeamScreen(services)
    screen._team_id = "team-123"  # simulate the async task-load having resolved a team

    monkeypatch.setattr(services.auth, "access_token", lambda: None)
    screen._on_copy_mobile_link()
    assert "Sign in" in screen._mobile_link_status.text()


def test_copy_mobile_link_builds_url_with_team_project_and_token(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    project_uuid = services.projects.ensure_project_uuid(project.id)
    services.set_active_project(project.id)
    screen = TeamScreen(services)
    screen._team_id = "team-123"

    monkeypatch.setattr(services.auth, "access_token", lambda: "fake-jwt-token")
    monkeypatch.setattr(
        "spiced.ui.screens.team.backend_config.backend_base_url",
        lambda: "http://localhost:8000",
    )
    screen._on_copy_mobile_link()

    copied = QApplication.clipboard().text()
    assert copied == (
        f"http://localhost:8000/mobile/teams/team-123?project_uuid={project_uuid}"
        "&token=fake-jwt-token"
    )
    assert "copied" in screen._mobile_link_status.text().lower()
