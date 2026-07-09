"""Build-readiness heuristic tests.

These exercise ``assess_readiness`` directly with hand-built inputs so each
label (Not enough data, Needs review, Stabilizing, Demo candidate) and its
evidence/caveats are pinned down independently of the storage layer.
"""

from dataclasses import dataclass

from spiced.core.dashboard import (
    DEMO_CANDIDATE,
    NEEDS_REVIEW,
    NOT_ENOUGH_DATA,
    STABILIZING,
    _TestCounts,
    assess_readiness,
)


@dataclass
class _FakeSession:
    detected_error_type: str | None = None
    detected_file: str | None = None
    detected_line: int | None = None


@dataclass
class _FakeRun:
    parsed_summary: dict


def _counts(total=0, passed=0, failed=0, blocked=0, not_run=0):
    return _TestCounts(total, passed, failed, blocked, not_run)


def test_no_data_is_not_enough_data():
    result = assess_readiness(
        sessions=[],
        counts=_counts(),
        latest_run=None,
        has_feedback=False,
        feedback_counts={},
    )
    assert result.label == NOT_ENOUGH_DATA
    assert result.caveats


def test_failing_run_is_needs_review():
    run = _FakeRun({"total": 5, "passed": 3, "failed": 2, "skipped": 0, "failures": ["x"]})
    result = assess_readiness(
        sessions=[],
        counts=_counts(),
        latest_run=run,
        has_feedback=False,
        feedback_counts={},
    )
    assert result.label == NEEDS_REVIEW
    assert any("failing test" in e for e in result.evidence)
    assert result.caveats


def test_failing_case_is_needs_review():
    result = assess_readiness(
        sessions=[],
        counts=_counts(total=3, passed=1, failed=1, blocked=0, not_run=1),
        latest_run=None,
        has_feedback=False,
        feedback_counts={},
    )
    assert result.label == NEEDS_REVIEW
    assert any("Fail" in e for e in result.evidence)


def test_blocked_case_is_needs_review():
    result = assess_readiness(
        sessions=[],
        counts=_counts(total=2, passed=1, failed=0, blocked=1, not_run=0),
        latest_run=None,
        has_feedback=False,
        feedback_counts={},
    )
    assert result.label == NEEDS_REVIEW
    assert any("Blocked" in e for e in result.evidence)


def test_high_risk_debug_error_is_needs_review():
    session = _FakeSession(
        detected_error_type="NullReferenceException",
        detected_file="HealthPickup.cs",
        detected_line=24,
    )
    result = assess_readiness(
        sessions=[session],
        counts=_counts(),
        latest_run=None,
        has_feedback=False,
        feedback_counts={},
    )
    assert result.label == NEEDS_REVIEW
    assert any("HealthPickup.cs:24" in e for e in result.evidence)


def test_bug_feedback_is_needs_review():
    result = assess_readiness(
        sessions=[],
        counts=_counts(),
        latest_run=None,
        has_feedback=True,
        feedback_counts={"Bug or technical issue": 2},
    )
    assert result.label == NEEDS_REVIEW
    assert any("bug/performance" in e for e in result.evidence)


def test_passing_run_plus_soft_feedback_is_stabilizing():
    run = _FakeRun({"total": 5, "passed": 5, "failed": 0, "skipped": 0, "failures": []})
    result = assess_readiness(
        sessions=[],
        counts=_counts(),
        latest_run=run,
        has_feedback=True,
        feedback_counts={"Confusion or onboarding issue": 1, "Praise": 2},
    )
    assert result.label == STABILIZING
    # Confusion is surfaced as a soft signal, not a blocking problem.
    assert any("confusion" in e for e in result.evidence)


def test_clean_across_three_modules_is_demo_candidate():
    run = _FakeRun({"total": 6, "passed": 6, "failed": 0, "skipped": 0, "failures": []})
    # Debug session present but with no specific detected error (not high-risk).
    result = assess_readiness(
        sessions=[_FakeSession()],
        counts=_counts(total=2, passed=2, failed=0, blocked=0, not_run=0),
        latest_run=run,
        has_feedback=True,
        feedback_counts={"Praise": 4},
    )
    assert result.label == DEMO_CANDIDATE
    # Even the best label keeps an explicit uncertainty caveat.
    assert result.caveats


def test_demo_candidate_downgrades_to_stabilizing_with_confusion():
    run = _FakeRun({"total": 6, "passed": 6, "failed": 0, "skipped": 0, "failures": []})
    result = assess_readiness(
        sessions=[_FakeSession()],
        counts=_counts(total=2, passed=2, failed=0, blocked=0, not_run=0),
        latest_run=run,
        has_feedback=True,
        feedback_counts={"Praise": 4, "Confusion or onboarding issue": 1},
    )
    assert result.label == STABILIZING


def test_single_module_of_positive_data_is_not_enough():
    # Passing tests but no other module — not enough coverage to judge.
    result = assess_readiness(
        sessions=[],
        counts=_counts(total=2, passed=2, failed=0, blocked=0, not_run=0),
        latest_run=None,
        has_feedback=False,
        feedback_counts={},
    )
    assert result.label == NOT_ENOUGH_DATA


def test_no_assessment_ever_claims_ship_ready():
    run = _FakeRun({"total": 6, "passed": 6, "failed": 0, "skipped": 0, "failures": []})
    result = assess_readiness(
        sessions=[_FakeSession()],
        counts=_counts(total=2, passed=2, failed=0, blocked=0, not_run=0),
        latest_run=run,
        has_feedback=True,
        feedback_counts={"Praise": 4},
    )
    blob = " ".join([result.label, *result.evidence, *result.caveats]).lower()
    assert "ready to ship" not in blob or "not a guarantee" in blob
    assert "ship ready" not in blob
