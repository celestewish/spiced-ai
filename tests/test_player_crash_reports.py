"""Tests for core.player_crash_reports: syncing player-submitted crashes
into Known Issues, idempotently, tagged source="player".

TeamService is faked so no real backend/network call happens.
"""

from __future__ import annotations

from spiced.backend_client.api_client import (
    BackendAPIError,
    NotAuthenticatedError,
    PlayerCrashReport,
)
from spiced.core.player_crash_reports import PlayerCrashSyncService
from spiced.core.regression import RegressionService
from spiced.storage.database import Database
from spiced.storage.known_issues import SOURCE_PLAYER, KnownIssueRepository
from spiced.storage.player_crash_sync import PlayerCrashSyncRepository
from spiced.storage.projects import ProjectRepository


class FakeTeamService:
    def __init__(self, reports=None, raise_error=None):
        self._reports = reports or []
        self._raise_error = raise_error
        self.notify_calls: list[tuple] = []

    def list_player_crashes(self, project_uuid):
        if self._raise_error is not None:
            raise self._raise_error
        return self._reports

    def notify_relevant_members_for_project_event(
        self, project_uuid, event_kind, title, body, **kwargs
    ):
        self.notify_calls.append((project_uuid, event_kind, title, body, kwargs))
        return []


def _report(report_id, error_type="NullReferenceException", message="boom"):
    return PlayerCrashReport(
        id=report_id,
        project_uuid="proj-uuid",
        error_type=error_type,
        message=message,
        stack_excerpt=None,
        app_version="1.0.0",
        occurred_at="2026-08-01T00:00:00Z",
        reported_at="2026-08-01T00:01:00Z",
    )


def _service(team_service):
    db = Database(":memory:")
    regression = RegressionService(KnownIssueRepository(db))
    sync_log = PlayerCrashSyncRepository(db)
    return PlayerCrashSyncService(team_service, regression, sync_log), regression, db


def test_sync_ingests_new_reports_into_known_issues():
    service, regression, db = _service(FakeTeamService(reports=[_report("r1")]))
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")

    result = service.sync(project.id, "proj-uuid")

    assert result.fetched_count == 1
    assert len(result.new_outcomes) == 1
    issues = regression.list_for_project(project.id)
    assert len(issues) == 1
    assert issues[0].source == SOURCE_PLAYER
    assert "NullReferenceException" in issues[0].title


def test_sync_is_idempotent_across_repeated_calls():
    service, regression, db = _service(FakeTeamService(reports=[_report("r1")]))
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")

    first = service.sync(project.id, "proj-uuid")
    second = service.sync(project.id, "proj-uuid")

    assert len(first.new_outcomes) == 1
    assert len(second.new_outcomes) == 0  # already ingested, not double-counted
    issues = regression.list_for_project(project.id)
    assert issues[0].occurrences == 1  # never inflated by a repeat sync


def test_sync_only_ingests_reports_not_seen_before():
    team_service = FakeTeamService(reports=[_report("r1")])
    service, regression, db = _service(team_service)
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")

    service.sync(project.id, "proj-uuid")
    team_service._reports = [_report("r1"), _report("r2", error_type="IndexOutOfRange")]
    second = service.sync(project.id, "proj-uuid")

    assert second.fetched_count == 2
    assert len(second.new_outcomes) == 1  # only r2 is new
    issues = regression.list_for_project(project.id)
    assert len(issues) == 2


def test_sync_swallows_backend_errors_and_returns_nothing_new():
    service, regression, db = _service(
        FakeTeamService(raise_error=BackendAPIError("backend down"))
    )
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")

    result = service.sync(project.id, "proj-uuid")

    assert result.fetched_count == 0
    assert result.new_outcomes == []
    assert regression.list_for_project(project.id) == []


def test_sync_swallows_auth_errors():
    service, regression, db = _service(
        FakeTeamService(raise_error=NotAuthenticatedError("not signed in"))
    )
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")

    result = service.sync(project.id, "proj-uuid")
    assert result.fetched_count == 0


def test_sync_notifies_relevant_members_for_a_brand_new_issue():
    team_service = FakeTeamService(reports=[_report("r1")])
    service, _regression, db = _service(team_service)
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")

    service.sync(project.id, "proj-uuid")

    assert len(team_service.notify_calls) == 1
    project_uuid, event_kind, title, _body, kwargs = team_service.notify_calls[0]
    assert project_uuid == "proj-uuid"
    assert event_kind == "known_issue_opened"
    assert "NullReferenceException" in title
    assert kwargs["subject_type"] == "known_issue"


def test_sync_does_not_notify_for_a_repeat_of_an_already_open_issue():
    """A player crash matching an already-open (not resolved) known issue is
    a repeat occurrence, not new news -- no notification."""
    from spiced.core.regression import debug_signature

    team_service = FakeTeamService(reports=[_report("r1")])
    service, regression, db = _service(team_service)
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    regression.note_issue(
        project.id, "debug", debug_signature("NullReferenceException", None),
        "NullReferenceException in Foo.cs",
    )

    service.sync(project.id, "proj-uuid")

    assert team_service.notify_calls == []


def test_sync_notifies_regression_for_a_resolved_issue_reoccurring():
    from spiced.core.regression import debug_signature

    team_service = FakeTeamService(reports=[_report("r1")])
    service, regression, db = _service(team_service)
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    issue = regression.note_issue(
        project.id, "debug", debug_signature("NullReferenceException", None),
        "NullReferenceException in Foo.cs",
    ).issue
    regression.mark_resolved(issue.id)

    service.sync(project.id, "proj-uuid")

    assert len(team_service.notify_calls) == 1
    assert team_service.notify_calls[0][1] == "known_issue_regression"


def test_sync_matches_similar_signature_to_existing_dev_found_issue():
    """A player crash with the same error type as a dev-diagnosed issue
    should surface as a match through the same signature pipeline — the
    spec calls for crash reports to feed into the *same* bug-tracking flow,
    not a separate player-only list."""
    service, regression, db = _service(FakeTeamService(reports=[_report("r1")]))
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")

    from spiced.core.regression import debug_signature

    dev_signature = debug_signature("NullReferenceException", None)
    regression.note_issue(project.id, "debug", dev_signature, "NullReferenceException in Foo.cs")

    result = service.sync(project.id, "proj-uuid")
    assert len(result.new_outcomes) == 1
    outcome = result.new_outcomes[0]
    assert outcome.match is not None  # matched the pre-existing dev-found issue
