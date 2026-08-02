"""Storage round-trip tests for the Phase 6 repositories.

Follows the same pattern as test_test_runs.py / test_feedback_batches.py: a
fresh in-memory database per test, create -> get/list round trips, and
project-scoping checks.
"""

from spiced.storage.accessibility_reports import AccessibilityReportRepository
from spiced.storage.code_health_reports import CodeHealthReportRepository
from spiced.storage.community_pulse import CommunityPulseRepository
from spiced.storage.database import Database
from spiced.storage.feedback_tasks import STATUS_ACCEPTED, STATUS_DRAFT, FeedbackTaskRepository
from spiced.storage.known_issues import STATUS_OPEN, STATUS_RESOLVED, KnownIssueRepository
from spiced.storage.performance_reports import PerformanceReportRepository
from spiced.storage.projects import ProjectRepository
from spiced.storage.version_check_reports import VersionCheckReportRepository


def _project(db):
    return ProjectRepository(db).create("Moonlit Depths", engine="Unity")


# --- known_issues -----------------------------------------------------------


def test_known_issue_upsert_creates_then_increments_occurrences():
    db = Database(":memory:")
    issues = KnownIssueRepository(db)
    project = _project(db)
    first = issues.upsert(project.id, "sig-1", "debug", "NullReferenceException in Foo.cs")
    assert first.occurrences == 1
    assert first.status == STATUS_OPEN
    second = issues.upsert(project.id, "sig-1", "debug", "NullReferenceException in Foo.cs")
    assert second.id == first.id
    assert second.occurrences == 2


def test_known_issue_resolve_and_reopen():
    db = Database(":memory:")
    issues = KnownIssueRepository(db)
    project = _project(db)
    issue = issues.upsert(project.id, "sig-1", "test", "Player takes damage")
    resolved = issues.mark_resolved(issue.id)
    assert resolved.status == STATUS_RESOLVED
    assert resolved.resolved_at is not None
    reopened = issues.mark_open(issue.id)
    assert reopened.status == STATUS_OPEN
    assert reopened.resolved_at is None


def test_known_issue_list_scoped_and_ordered():
    db = Database(":memory:")
    issues = KnownIssueRepository(db)
    project = _project(db)
    issues.upsert(project.id, "sig-a", "test", "A")
    issues.upsert(project.id, "sig-b", "test", "B")
    listed = issues.list_for_project(project.id)
    assert {i.signature for i in listed} == {"sig-a", "sig-b"}


# --- performance_reports ------------------------------------------------------


def test_performance_report_round_trip():
    db = Database(":memory:")
    reports = PerformanceReportRepository(db)
    project = _project(db)
    report = reports.create(
        project_id=project.id,
        source_type="paste",
        target_hardware="Low-end PC",
        parsed_summary={"avg_fps": 41.5},
        spikes=[{"location": "Dock", "metric": "fps", "value": 25, "severity": "severe"}],
        ai_summary="Frame drops near the dock.",
        provider="mock",
    )
    fetched = reports.get(report.id)
    assert fetched.target_hardware == "Low-end PC"
    assert fetched.parsed_summary["avg_fps"] == 41.5
    assert fetched.spikes[0]["location"] == "Dock"
    assert reports.list_for_project(project.id)[0].id == report.id


# --- accessibility_reports ----------------------------------------------------


def test_accessibility_report_round_trip():
    db = Database(":memory:")
    reports = AccessibilityReportRepository(db)
    project = _project(db)
    report = reports.create(
        project_id=project.id,
        source_type="paste",
        parsed_summary={"score": 80},
        findings=[{"check": "captions", "message": "1 missing", "severity": "warn"}],
        score=80,
        ai_summary="Mostly solid.",
    )
    fetched = reports.get(report.id)
    assert fetched.score == 80
    assert fetched.findings[0]["check"] == "captions"


# --- version_check_reports -----------------------------------------------------


def test_version_check_report_round_trip():
    db = Database(":memory:")
    reports = VersionCheckReportRepository(db)
    project = _project(db)
    report = reports.create(
        project_id=project.id,
        source_filename="Player.cs",
        hits=[{"line_number": 3, "api_name": "WWW"}],
        ai_summary="One outdated API found.",
    )
    fetched = reports.get(report.id)
    assert fetched.source_filename == "Player.cs"
    assert fetched.hits[0]["api_name"] == "WWW"


# --- code_health_reports -------------------------------------------------------


def test_code_health_report_round_trip():
    db = Database(":memory:")
    reports = CodeHealthReportRepository(db)
    project = _project(db)
    report = reports.create(
        project_id=project.id,
        metrics={"line_count": 40, "function_count": 2},
        ai_summary="Looks manageable.",
    )
    fetched = reports.get(report.id)
    assert fetched.metrics["line_count"] == 40


# --- feedback_tasks -------------------------------------------------------------


def test_feedback_task_create_edit_and_status():
    db = Database(":memory:")
    tasks = FeedbackTaskRepository(db)
    project = _project(db)
    task = tasks.create(project.id, "Bug or technical issue", "Investigate the jump bug")
    assert task.status == STATUS_DRAFT
    edited = tasks.update_text(task.id, "Investigate the jump bug more carefully")
    assert edited.text == "Investigate the jump bug more carefully"
    accepted = tasks.set_status(task.id, STATUS_ACCEPTED)
    assert accepted.status == STATUS_ACCEPTED
    tasks.delete(task.id)
    assert tasks.list_for_project(project.id) == []


# --- community_pulse_checkins ---------------------------------------------------


def test_community_pulse_checkin_round_trip():
    db = Database(":memory:")
    checkins = CommunityPulseRepository(db)
    project = _project(db)
    checkin = checkins.create(
        project_id=project.id,
        source="mock",
        channel_label="#mock-community (offline sample data)",
        message_count=5,
        raw_excerpt="ari: nice work",
        ai_summary="Generally positive.",
        provider="mock",
    )
    fetched = checkins.get(checkin.id)
    assert fetched.message_count == 5
    assert fetched.channel_label.startswith("#mock-community")
    assert checkins.list_for_project(project.id)[0].id == checkin.id
