"""Solo-Dev Mode vs. Small-Team Mode toggle: settings round-trip plus the
solo-safe defaults of team_prompt_context()/sync_session_summary().
"""

from __future__ import annotations

from spiced.app.services import Services
from spiced.storage.session_summaries import SessionSummary


def _services() -> Services:
    return Services(":memory:")


def test_team_mode_disabled_by_default():
    services = _services()
    assert services.team_mode_enabled() is False


def test_team_mode_toggle_round_trips():
    services = _services()
    services.set_team_mode_enabled(True)
    assert services.team_mode_enabled() is True
    services.set_team_mode_enabled(False)
    assert services.team_mode_enabled() is False


def test_team_prompt_context_none_when_team_mode_off():
    services = _services()
    project = services.projects.create_project("Moonlit Depths")
    assert services.team_prompt_context(project) is None


def test_team_prompt_context_none_without_active_project():
    services = _services()
    services.set_team_mode_enabled(True)
    assert services.team_prompt_context(None) is None


def test_team_prompt_context_none_for_unlinked_project():
    services = _services()
    services.set_team_mode_enabled(True)
    project = services.projects.create_project("Moonlit Depths")
    assert project.project_uuid is None
    assert services.team_prompt_context(project) is None


def test_team_prompt_context_none_when_signed_out():
    services = _services()
    services.set_team_mode_enabled(True)
    project = services.projects.create_project("Moonlit Depths")
    services.projects.ensure_project_uuid(project.id)
    linked = services.projects.get_project(project.id)
    assert not services.auth.is_logged_in()
    assert services.team_prompt_context(linked) is None


def test_sync_session_summary_false_when_team_mode_off():
    services = _services()
    project = services.projects.create_project("Moonlit Depths")
    summary = SessionSummary(
        id=1,
        project_id=project.id,
        started_at="2026-08-03 09:00:00",
        ended_at="2026-08-03 10:00:00",
        tested_summary=None,
        fixed_summary=None,
        open_summary=None,
        ai_summary="Recap.",
        synced_to_team=False,
        created_at="2026-08-03 10:00:00",
    )
    assert services.sync_session_summary(project, summary) is False


def test_sync_session_summary_false_when_project_unlinked():
    services = _services()
    services.set_team_mode_enabled(True)
    project = services.projects.create_project("Moonlit Depths")
    summary = SessionSummary(
        id=1,
        project_id=project.id,
        started_at="2026-08-03 09:00:00",
        ended_at="2026-08-03 10:00:00",
        tested_summary=None,
        fixed_summary=None,
        open_summary=None,
        ai_summary="Recap.",
        synced_to_team=False,
        created_at="2026-08-03 10:00:00",
    )
    assert services.sync_session_summary(project, summary) is False
