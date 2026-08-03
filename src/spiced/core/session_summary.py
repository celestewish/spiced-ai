"""Session Summaries: a devlog-style recap of what changed since the last one.

Gathers already-stored, compact evidence from TestingService (test runs,
manual test cases, known issues) and FeedbackService (pending tasks) — never
raw logs or full feedback text — then asks the AI provider for a short
"tested / fixed / still open" recap, following the same local-evidence-first
pattern as every other Spiced prompt in this app.

Team-sync note: this module only ever produces and stores the *summary*
locally. Whether that summary also gets posted to the team backend is decided
by the caller (app/services.py), which is also the only place that knows
about Team Mode and team-linking — this service stays usable in Solo-Dev
Mode with no notion of teams at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_session_summary_prompt
from spiced.core.feedback import FeedbackService
from spiced.core.testing import TestingService
from spiced.storage.known_issues import STATUS_OPEN, STATUS_RESOLVED
from spiced.storage.projects import Project
from spiced.storage.session_summaries import SessionSummary, SessionSummaryRepository

_MAX_ITEMS = 8


@dataclass(frozen=True)
class SessionWindow:
    """Deterministic, locally-gathered evidence for one summary."""

    since: str
    tested: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.tested or self.fixed or self.open_items)


@dataclass(frozen=True)
class SessionSummaryResult:
    window: SessionWindow
    response_text: str
    provider: str
    summary: SessionSummary


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


def now_sqlite() -> str:
    """A timestamp string in the same lexicographically-sortable format
    SQLite's ``datetime('now')`` produces, so window boundaries compare
    correctly against ``created_at``/``updated_at`` columns."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class SessionSummaryService:
    """Gathers a session's evidence window and turns it into a saved summary."""

    def __init__(
        self,
        summaries: SessionSummaryRepository,
        testing: TestingService,
        feedback: FeedbackService,
    ) -> None:
        self._summaries = summaries
        self._testing = testing
        self._feedback = feedback

    def window_since(self, project_id: int, app_started_at: str) -> str:
        """The boundary to gather evidence from: the previous summary's
        ``ended_at``, or app-session start if this project has no summary yet.
        """
        latest = self._summaries.latest_for_project(project_id)
        return latest.ended_at if latest is not None else app_started_at

    def gather_window(self, project_id: int, app_started_at: str) -> SessionWindow:
        since = self.window_since(project_id, app_started_at)

        tested: list[str] = []
        for run in self._testing.history(project_id, limit=20):
            if run.created_at < since:
                continue
            s = run.parsed_summary
            label = f"Test run: {s.get('passed', 0)} passed / {s.get('failed', 0)} failed"
            if run.source_filename:
                label += f" ({run.source_filename})"
            tested.append(label)
        for case in self._testing.list_cases(project_id):
            if case.status != "Not Run" and case.updated_at >= since:
                tested.append(f"{case.title}: {case.status}")

        fixed: list[str] = []
        open_items: list[str] = []
        for issue in self._testing.known_issues(project_id):
            if issue.status == STATUS_RESOLVED:
                if issue.resolved_at and issue.resolved_at >= since:
                    fixed.append(issue.title)
            elif issue.status == STATUS_OPEN:
                open_items.append(issue.title)

        for task in self._feedback.list_tasks(project_id):
            if task.status == "draft":
                open_items.append(f"Feedback task: {task.text}")

        return SessionWindow(
            since=since,
            tested=tested[:_MAX_ITEMS],
            fixed=fixed[:_MAX_ITEMS],
            open_items=open_items[:_MAX_ITEMS],
        )

    def summarize(
        self,
        provider: AIProvider,
        project: Project,
        app_started_at: str,
        *,
        team_mode: bool = False,
        team_members: list[str] | None = None,
        record_usage=None,
    ) -> SessionSummaryResult:
        """Gather the window, ask the provider for a recap, and save it.

        ``record_usage`` is an optional callback invoked with the provider
        name after a successful reply, so the usage counter can increment.
        """
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in "
                "Settings for free offline summaries."
            )

        window = self.gather_window(project.id, app_started_at)
        prompt = build_session_summary_prompt(
            since=window.since,
            tested=window.tested,
            fixed=window.fixed,
            open_items=window.open_items,
            project_name=project.name,
            team_mode=team_mode,
            team_members=team_members,
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        summary = self._summaries.create(
            project_id=project.id,
            started_at=window.since,
            ended_at=now_sqlite(),
            tested_summary=_join(window.tested),
            fixed_summary=_join(window.fixed),
            open_summary=_join(window.open_items),
            ai_summary=response.text,
        )
        return SessionSummaryResult(
            window=window,
            response_text=response.text,
            provider=response.provider,
            summary=summary,
        )

    def history(self, project_id: int, limit: int = 20) -> list[SessionSummary]:
        return self._summaries.list_for_project(project_id, limit=limit)

    def mark_synced(self, summary_id: int) -> SessionSummary:
        return self._summaries.mark_synced(summary_id)


def _join(items: list[str]) -> str | None:
    return "; ".join(items) if items else None
