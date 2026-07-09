"""Project dashboard: a deterministic, local-first synthesis of what Spiced
knows about the active project.

This module reads already-stored, compact records (debug sessions, test cases,
test runs, feedback batches) and turns them into a calm overview: module status
cards, a cautious build-readiness label with its evidence, a human-approved
review queue of next actions, and friendly setup reminders when data is missing.

Everything here is deterministic and offline — no AI, no network. The readiness
label is a planning aid, never a claim that a game is objectively ready to ship;
the developer stays the decision-maker.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spiced.storage.debug_sessions import DebugSession
from spiced.storage.feedback_batches import FeedbackBatch
from spiced.storage.projects import Project
from spiced.storage.test_cases import TestCase
from spiced.storage.test_runs import TestRun

# --- Readiness labels (cautious by design) ---------------------------------
NOT_ENOUGH_DATA = "Not enough data"
NEEDS_REVIEW = "Needs review"
STABILIZING = "Stabilizing"
DEMO_CANDIDATE = "Demo candidate"

# --- Next-action source modules --------------------------------------------
MODULE_DEBUGGING = "Debugging"
MODULE_TESTING = "Testing"
MODULE_FEEDBACK = "Feedback"
MODULE_PROJECT = "Project"

# --- Priorities ------------------------------------------------------------
PRIORITY_LOW = "Low"
PRIORITY_MEDIUM = "Medium"
PRIORITY_HIGH = "High"
_PRIORITY_ORDER = {PRIORITY_HIGH: 0, PRIORITY_MEDIUM: 1, PRIORITY_LOW: 2}

# Local feedback categories treated as technical problems (must match the
# labels produced by spiced.core.feedback_classifier).
_FEEDBACK_BUG = "Bug or technical issue"
_FEEDBACK_CONFUSION = "Confusion or onboarding issue"
_FEEDBACK_PERFORMANCE = "Performance concern"
_FEEDBACK_PRAISE = "Praise"

_MAX_ACTIONS = 8


@dataclass(frozen=True)
class ModuleCard:
    name: str
    headline: str
    lines: list[str] = field(default_factory=list)
    is_empty: bool = False


@dataclass(frozen=True)
class NextAction:
    title: str
    source_module: str
    reason: str
    priority: str
    related_id: int | None = None


@dataclass(frozen=True)
class ReadinessAssessment:
    label: str
    evidence: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DashboardSummary:
    project_name: str
    engine: str
    unity_status: str
    project_path: str | None
    debugging: ModuleCard
    testing: ModuleCard
    feedback: ModuleCard
    readiness: ReadinessAssessment
    next_actions: list[NextAction] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        return _render_markdown(self)


@dataclass(frozen=True)
class _TestCounts:
    total: int
    passed: int
    failed: int
    blocked: int
    not_run: int


class DashboardService:
    """Builds a live, deterministic dashboard summary from stored data."""

    def __init__(self, debugging, testing, feedback) -> None:
        self._debugging = debugging
        self._testing = testing
        self._feedback = feedback

    def summarize(self, project: Project | None) -> DashboardSummary | None:
        """Return a summary for ``project``, or None when none is active."""
        if project is None:
            return None
        sessions = self._debugging.history(project.id, limit=10)
        cases = self._testing.list_cases(project.id)
        runs = self._testing.history(project.id, limit=10)
        batches = self._feedback.history(project.id, limit=10)
        return build_summary(project, sessions, cases, runs, batches)

    def summary_markdown(self, project: Project | None) -> str:
        summary = self.summarize(project)
        if summary is None:
            return "No active project selected."
        return summary.to_markdown()


# --- Pure builders (easy to test in isolation) -----------------------------


def build_summary(
    project: Project,
    sessions: list[DebugSession],
    cases: list[TestCase],
    runs: list[TestRun],
    batches: list[FeedbackBatch],
) -> DashboardSummary:
    counts = _count_cases(cases)
    latest_run = runs[0] if runs else None
    feedback_counts = _aggregate_feedback(batches)

    readiness = assess_readiness(
        sessions=sessions,
        counts=counts,
        latest_run=latest_run,
        has_feedback=bool(batches),
        feedback_counts=feedback_counts,
    )
    actions = build_next_actions(sessions, cases, latest_run, batches, feedback_counts)
    missing = _missing_data(project, sessions, cases, runs, batches)

    return DashboardSummary(
        project_name=project.name,
        engine=project.engine,
        unity_status=_unity_status(project),
        project_path=project.path,
        debugging=_debug_card(sessions),
        testing=_testing_card(counts, latest_run),
        feedback=_feedback_card(batches, feedback_counts),
        readiness=readiness,
        next_actions=actions,
        missing_data=missing,
    )


def assess_readiness(
    *,
    sessions: list[DebugSession],
    counts: _TestCounts,
    latest_run: TestRun | None,
    has_feedback: bool,
    feedback_counts: dict[str, int],
) -> ReadinessAssessment:
    """A cautious, explainable readiness label — a planning aid, not a verdict."""
    has_debug = bool(sessions)
    has_testing = counts.total > 0 or latest_run is not None
    modules_with_data = sum((has_debug, has_testing, has_feedback))

    caveat = (
        "This is a local planning aid based only on the data you've captured, not a "
        "guarantee the build is ready to ship. You decide what to do next."
    )

    if modules_with_data == 0:
        return ReadinessAssessment(
            NOT_ENOUGH_DATA,
            evidence=["No debugging, testing, or feedback data has been captured yet."],
            caveats=[caveat],
        )

    evidence: list[str] = []
    run_failed = int(latest_run.parsed_summary.get("failed", 0)) if latest_run else 0
    high_risk_debug = [s for s in sessions if s.detected_error_type]
    bug_feedback = feedback_counts.get(_FEEDBACK_BUG, 0) + feedback_counts.get(
        _FEEDBACK_PERFORMANCE, 0
    )
    confusion_feedback = feedback_counts.get(_FEEDBACK_CONFUSION, 0)

    problems = False
    if run_failed > 0:
        problems = True
        evidence.append(f"The latest test run has {run_failed} failing test(s).")
    if counts.failed > 0:
        problems = True
        evidence.append(f"{counts.failed} test case(s) are marked Fail.")
    if counts.blocked > 0:
        problems = True
        evidence.append(f"{counts.blocked} test case(s) are Blocked.")
    if high_risk_debug:
        problems = True
        top = high_risk_debug[0]
        where = _where(top)
        evidence.append(
            f"A recent debug session flagged {top.detected_error_type}"
            + (f" in {where}" if where else "")
            + "."
        )
    if bug_feedback > 0:
        problems = True
        evidence.append(f"Feedback includes {bug_feedback} likely bug/performance report(s).")

    if problems:
        if confusion_feedback:
            evidence.append(
                f"Feedback also mentions {confusion_feedback} confusion/onboarding point(s)."
            )
        return ReadinessAssessment(NEEDS_REVIEW, evidence=evidence, caveats=[caveat])

    # No hard problems. Judge coverage and positive signals.
    passing = (run_failed == 0 and latest_run is not None and _run_total(latest_run) > 0) or (
        counts.passed > 0 and counts.failed == 0 and counts.blocked == 0
    )

    if modules_with_data >= 2 and passing:
        if latest_run is not None and _run_total(latest_run) > 0:
            evidence.append("The latest test run has no failing tests.")
        if counts.passed > 0:
            evidence.append(f"{counts.passed} test case(s) are passing.")
        if not high_risk_debug and has_debug:
            evidence.append("No recent debug session flagged a specific error.")
        if has_feedback and bug_feedback == 0:
            evidence.append("Feedback shows no repeated bug reports.")

        demo = (
            modules_with_data == 3
            and not high_risk_debug
            and has_feedback
            and bug_feedback == 0
            and confusion_feedback == 0
        )
        if demo:
            return ReadinessAssessment(DEMO_CANDIDATE, evidence=evidence, caveats=[caveat])
        if confusion_feedback:
            evidence.append(
                f"Feedback still mentions {confusion_feedback} confusion/onboarding point(s)."
            )
        return ReadinessAssessment(STABILIZING, evidence=evidence, caveats=[caveat])

    evidence.append(
        "There is some data, but not enough recent testing/feedback across modules to judge "
        "readiness with confidence."
    )
    return ReadinessAssessment(NOT_ENOUGH_DATA, evidence=evidence, caveats=[caveat])


def build_next_actions(
    sessions: list[DebugSession],
    cases: list[TestCase],
    latest_run: TestRun | None,
    batches: list[FeedbackBatch],
    feedback_counts: dict[str, int],
) -> list[NextAction]:
    """Turn stored evidence into a human-approved review queue (recommendations)."""
    actions: list[NextAction] = []

    if latest_run is not None:
        failures = latest_run.parsed_summary.get("failures") or []
        for name in failures[:3]:
            actions.append(
                NextAction(
                    title=f"Retest and investigate: {name}",
                    source_module=MODULE_TESTING,
                    reason="This test failed in your latest recorded test run.",
                    priority=PRIORITY_HIGH,
                    related_id=latest_run.id,
                )
            )

    for case in cases:
        if case.status == "Fail":
            actions.append(
                NextAction(
                    title=f"Re-verify failing test case: {case.title}",
                    source_module=MODULE_TESTING,
                    reason=case.failure_note or "This manual test case is marked Fail.",
                    priority=PRIORITY_HIGH,
                    related_id=case.id,
                )
            )
        elif case.status == "Blocked":
            actions.append(
                NextAction(
                    title=f"Unblock test case: {case.title}",
                    source_module=MODULE_TESTING,
                    reason="This manual test case is Blocked and cannot be verified yet.",
                    priority=PRIORITY_MEDIUM,
                    related_id=case.id,
                )
            )

    for session in sessions:
        if session.detected_error_type:
            where = _where(session)
            title = f"Review the latest {session.detected_error_type}"
            if where:
                title += f" in {where}"
            actions.append(
                NextAction(
                    title=title,
                    source_module=MODULE_DEBUGGING,
                    reason="A recent debug session detected this error; confirm it is resolved.",
                    priority=PRIORITY_HIGH,
                    related_id=session.id,
                )
            )
            break  # one debugging action is enough to avoid noise

    bug_feedback = feedback_counts.get(_FEEDBACK_BUG, 0) + feedback_counts.get(
        _FEEDBACK_PERFORMANCE, 0
    )
    if bug_feedback > 0:
        actions.append(
            NextAction(
                title="Investigate bug/performance reports from player feedback",
                source_module=MODULE_FEEDBACK,
                reason=f"Feedback includes {bug_feedback} likely technical report(s).",
                priority=PRIORITY_HIGH,
                related_id=batches[0].id if batches else None,
            )
        )
    if feedback_counts.get(_FEEDBACK_CONFUSION, 0) > 0:
        actions.append(
            NextAction(
                title="Review onboarding/UX for repeated player confusion",
                source_module=MODULE_FEEDBACK,
                reason="Feedback repeatedly mentions confusion or onboarding issues.",
                priority=PRIORITY_MEDIUM,
                related_id=batches[0].id if batches else None,
            )
        )

    actions.sort(key=lambda a: _PRIORITY_ORDER.get(a.priority, 1))
    return actions[:_MAX_ACTIONS]


# --- Helpers ---------------------------------------------------------------


def _count_cases(cases: list[TestCase]) -> _TestCounts:
    passed = sum(1 for c in cases if c.status == "Pass")
    failed = sum(1 for c in cases if c.status == "Fail")
    blocked = sum(1 for c in cases if c.status == "Blocked")
    not_run = sum(1 for c in cases if c.status == "Not Run")
    return _TestCounts(len(cases), passed, failed, blocked, not_run)


def _aggregate_feedback(batches: list[FeedbackBatch]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for batch in batches:
        counts = batch.parsed_summary.get("category_counts")
        if isinstance(counts, dict):
            for category, count in counts.items():
                try:
                    totals[category] = totals.get(category, 0) + int(count)
                except (TypeError, ValueError):
                    continue
    return totals


def _run_total(run: TestRun) -> int:
    try:
        return int(run.parsed_summary.get("total", 0))
    except (TypeError, ValueError):
        return 0


def _where(session: DebugSession) -> str | None:
    if session.detected_file and session.detected_line is not None:
        return f"{session.detected_file}:{session.detected_line}"
    return session.detected_file


def _unity_status(project: Project) -> str:
    if project.is_valid_unity:
        version = project.engine_metadata.get("unity_version")
        return f"Valid Unity folder (Unity {version})" if version else "Valid Unity folder"
    if project.path:
        return "Folder set, but not recognized as a Unity project"
    return "No Unity folder connected"


def _debug_card(sessions: list[DebugSession]) -> ModuleCard:
    if not sessions:
        return ModuleCard(
            "Debugging",
            "No debug sessions yet.",
            ["Analyze a Unity log in Debugging Buddy to capture error context."],
            is_empty=True,
        )
    lines = []
    for session in sessions[:3]:
        where = _where(session)
        label = session.detected_error_type or "No specific error detected"
        lines.append(f"{label}" + (f" — {where}" if where else ""))
    headline = f"{len(sessions)} recent debug session(s)."
    return ModuleCard("Debugging", headline, lines)


def _testing_card(counts: _TestCounts, latest_run: TestRun | None) -> ModuleCard:
    if counts.total == 0 and latest_run is None:
        return ModuleCard(
            "Automated Testing",
            "No test cases or runs yet.",
            ["Add or import test cases and record results in Automated Testing."],
            is_empty=True,
        )
    lines = []
    if counts.total > 0:
        lines.append(
            f"Test cases: {counts.passed} pass · {counts.failed} fail · "
            f"{counts.blocked} blocked · {counts.not_run} not run"
        )
    if latest_run is not None:
        s = latest_run.parsed_summary
        lines.append(
            "Latest run: "
            f"{s.get('total', 0)} total · {s.get('passed', 0)} passed · "
            f"{s.get('failed', 0)} failed · {s.get('skipped', 0)} skipped"
        )
    headline = f"{counts.total} manual test case(s)."
    return ModuleCard("Automated Testing", headline, lines)


def _feedback_card(batches: list[FeedbackBatch], counts: dict[str, int]) -> ModuleCard:
    if not batches:
        return ModuleCard(
            "Feedback Review",
            "No feedback batches yet.",
            ["Import player feedback in Feedback Review to spot themes and issues."],
            is_empty=True,
        )
    lines = []
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    if top:
        lines.append("Top categories: " + ", ".join(f"{name} ({n})" for name, n in top))
    latest = batches[0]
    themes = ", ".join(latest.themes[:3]) if latest.themes else ""
    if themes:
        lines.append(f"Recent themes: {themes}")
    total_entries = sum(b.entry_count for b in batches)
    headline = f"{len(batches)} feedback batch(es) · {total_entries} entries."
    return ModuleCard("Feedback Review", headline, lines)


def _missing_data(
    project: Project,
    sessions: list[DebugSession],
    cases: list[TestCase],
    runs: list[TestRun],
    batches: list[FeedbackBatch],
) -> list[str]:
    reminders: list[str] = []
    if not project.path:
        reminders.append("Connect a Unity folder so Spiced can show validation and version.")
    elif not project.is_valid_unity:
        reminders.append(
            "The saved folder isn't recognized as a Unity project — double-check the path."
        )
    if not sessions:
        reminders.append("Analyze a Unity log in Debugging Buddy to capture error context.")
    if not cases and not runs:
        reminders.append("Add or import test cases in Automated Testing.")
    if not batches:
        reminders.append("Import player feedback in Feedback Review.")
    return reminders


def _render_markdown(summary: DashboardSummary) -> str:
    lines = [
        f"# Project health: {summary.project_name}",
        "",
        f"- Engine: {summary.engine}",
        f"- Unity folder: {summary.unity_status}",
        f"- Build readiness: **{summary.readiness.label}**",
        "",
        "## Why",
    ]
    lines += [f"- {item}" for item in summary.readiness.evidence] or ["- (no evidence yet)"]

    lines += ["", "## Module highlights"]
    for card in (summary.debugging, summary.testing, summary.feedback):
        lines.append(f"### {card.name}")
        lines.append(f"- {card.headline}")
        lines += [f"- {line}" for line in card.lines]

    lines += ["", "## Recommended next actions"]
    if summary.next_actions:
        for action in summary.next_actions:
            lines.append(
                f"- [{action.priority}] {action.title} "
                f"({action.source_module}) — {action.reason}"
            )
    else:
        lines.append("- No specific actions yet. Capture more data to get recommendations.")

    lines += ["", "## What I would not assume yet"]
    lines += [f"- {c}" for c in summary.readiness.caveats]
    if summary.missing_data:
        lines += ["", "## Setup reminders"]
        lines += [f"- {item}" for item in summary.missing_data]

    lines += [
        "",
        "_Spiced synthesizes your local QA signals and suggests next steps. "
        "You remain the decision-maker._",
    ]
    return "\n".join(lines)
