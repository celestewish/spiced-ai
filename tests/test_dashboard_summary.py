"""Dashboard summary + build-readiness heuristic tests.

These build data through the real services against an in-memory database so the
DashboardService is exercised end to end, then assert the deterministic output.
"""

from spiced.core.dashboard import (
    DEMO_CANDIDATE,
    NEEDS_REVIEW,
    NOT_ENOUGH_DATA,
    STABILIZING,
    DashboardService,
)
from spiced.core.debugging import DebuggingService
from spiced.core.feedback import FeedbackService
from spiced.core.testing import TestingService
from spiced.storage.database import Database
from spiced.storage.debug_sessions import DebugSessionRepository
from spiced.storage.feedback_batches import FeedbackBatchRepository
from spiced.storage.projects import ProjectRepository
from spiced.storage.test_cases import TestCaseRepository
from spiced.storage.test_runs import TestRunRepository


def _fixture():
    db = Database(":memory:")
    project = ProjectRepository(db).create("Starfall Prototype", engine="Unity")
    debugging = DebuggingService(DebugSessionRepository(db))
    testing = TestingService(TestCaseRepository(db), TestRunRepository(db))
    feedback = FeedbackService(FeedbackBatchRepository(db))
    service = DashboardService(debugging, testing, feedback)
    return db, project, debugging, testing, feedback, service


def _add_debug(db, project, error_type="NullReferenceException", file="HealthPickup.cs", line=24):
    DebugSessionRepository(db).create(
        project_id=project.id,
        source_type="paste",
        summary="Something referenced a missing object.",
        detected_error_type=error_type,
        detected_file=file,
        detected_line=line,
    )


def _add_run(db, project, total=5, passed=2, failed=2, skipped=1, failures=None):
    TestRunRepository(db).create(
        project_id=project.id,
        source_type="paste",
        parsed_summary={
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "failures": failures or [],
        },
    )


def _add_feedback(db, project, counts, themes=None):
    FeedbackBatchRepository(db).create(
        project_id=project.id,
        source_type="paste",
        entry_count=sum(counts.values()),
        parsed_summary={"category_counts": counts},
        themes=themes,
    )


def test_no_active_project_returns_none():
    _, _, _, _, _, service = _fixture()
    assert service.summarize(None) is None


def test_no_data_is_not_enough_data():
    _, project, _, _, _, service = _fixture()
    summary = service.summarize(project)
    assert summary.readiness.label == NOT_ENOUGH_DATA
    assert summary.debugging.is_empty
    assert summary.testing.is_empty
    assert summary.feedback.is_empty
    # Friendly setup reminders across every module.
    assert any("Unity folder" in m for m in summary.missing_data)
    assert any("Debugging" in m for m in summary.missing_data)


def test_debug_only_summary_populates_debug_card():
    db, project, _, _, _, service = _fixture()
    _add_debug(db, project)
    summary = service.summarize(project)
    assert not summary.debugging.is_empty
    assert "NullReferenceException" in summary.debugging.lines[0]
    assert summary.testing.is_empty
    assert summary.feedback.is_empty


def test_tests_only_summary_populates_testing_card():
    db, project, _, testing, _, service = _fixture()
    case = testing.create_case(project_id=project.id, title="Player can move")
    testing.set_status(case.id, "Pass")
    summary = service.summarize(project)
    assert not summary.testing.is_empty
    assert summary.debugging.is_empty


def test_feedback_only_summary_populates_feedback_card():
    db, project, _, _, _, service = _fixture()
    _add_feedback(db, project, {"Praise": 3, "Confusion or onboarding issue": 1})
    summary = service.summarize(project)
    assert not summary.feedback.is_empty
    assert "Top categories" in summary.feedback.lines[0]


def test_needs_review_when_failing_tests_and_debug_and_confusion():
    db, project, _, _, _, service = _fixture()
    _add_debug(db, project)
    _add_run(db, project, failures=["Player takes damage from spikes"])
    _add_feedback(db, project, {"Confusion or onboarding issue": 2, "Praise": 1})
    summary = service.summarize(project)
    assert summary.readiness.label == NEEDS_REVIEW
    evidence = " ".join(summary.readiness.evidence)
    assert "failing test" in evidence
    assert "HealthPickup.cs:24" in evidence
    # Never claims the build is ready.
    assert summary.readiness.caveats


def test_stabilizing_when_passing_tests_and_soft_feedback_only():
    db, project, _, testing, _, service = _fixture()
    _add_run(db, project, total=5, passed=5, failed=0, skipped=0)
    _add_feedback(db, project, {"Confusion or onboarding issue": 1, "Praise": 2})
    summary = service.summarize(project)
    assert summary.readiness.label == STABILIZING


def test_demo_candidate_when_clean_across_modules():
    db, project, _, testing, _, service = _fixture()
    # Debug data present but with no specific detected error (not high-risk).
    DebugSessionRepository(db).create(
        project_id=project.id, source_type="paste", summary="Reviewed a clean log."
    )
    _add_run(db, project, total=6, passed=6, failed=0, skipped=0)
    case = testing.create_case(project_id=project.id, title="Jump feels good")
    testing.set_status(case.id, "Pass")
    _add_feedback(db, project, {"Praise": 4})
    summary = service.summarize(project)
    assert summary.readiness.label == DEMO_CANDIDATE
    # Even a demo candidate keeps an explicit uncertainty caveat.
    assert summary.readiness.caveats
