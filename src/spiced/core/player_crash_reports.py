"""Player Crash & Error Reporting sync (Phase G, section 7, Core tier).

Pulls crash/error reports real players of the shipped game sent in for a
team-linked project (see ``docs/player_crash_reporting.md`` for the exact
HTTP contract a game's own crash handler implements) and feeds each one
through the same signature-matching pipeline as internally found issues
(``core.regression``), tagged ``source="player"`` so the Known Issues panel
can show a visible "from players" badge. Only works for team-linked
projects — crash reporting needs a real ``project_uuid`` the backend
recognizes, and solo/local-only projects never mint one (consistent with
Spiced's local-first design: nothing about a purely local project is ever
reachable from outside this machine).

Notification Center event source (Phase K, section 9 part 1, #d): a player
crash that turns out to be a brand-new Known Issue, or a regression of a
previously-resolved one, also creates a real notification for whoever's
relevant to that event kind -- reusing the exact same "known_issue_opened"/
"known_issue_regression" routing Phase J already ships defaults for (see
``core.notification_routing.DEFAULT_EVENT_KIND_DISCIPLINES``). A repeat
occurrence of an already-open issue is deliberately quiet -- nothing new to
tell anyone.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.backend_client.api_client import (
    BackendAPIError,
    NotAuthenticatedError,
    PlayerCrashReport,
)
from spiced.core.regression import RegressionOutcome, RegressionService, debug_signature
from spiced.core.team_service import TeamService
from spiced.storage.known_issues import SOURCE_PLAYER
from spiced.storage.player_crash_sync import PlayerCrashSyncRepository

MAX_TITLE_CHARS = 300


class PlayerCrashSyncNotAvailableError(RuntimeError):
    """Raised when a project isn't eligible for player crash sync at all.

    Distinct from a flaky-network/auth failure (which ``sync()`` swallows
    and reports as "nothing new" rather than raising) — this is a plain,
    static fact about the project the caller can check before offering the
    action, e.g. to gray out a "Sync player crash reports" button.
    """


@dataclass(frozen=True)
class PlayerCrashSyncResult:
    fetched_count: int
    new_outcomes: list[RegressionOutcome]


class PlayerCrashSyncService:
    def __init__(
        self,
        teams: TeamService,
        regression: RegressionService,
        sync_log: PlayerCrashSyncRepository,
    ) -> None:
        self._teams = teams
        self._regression = regression
        self._sync_log = sync_log

    def sync(self, project_id: int, project_uuid: str) -> PlayerCrashSyncResult:
        """Fetch new player crash reports and merge them into Known Issues.

        Idempotent: each remote report id is only ever ingested once (see
        ``storage.player_crash_sync``), so occurrence counts don't inflate
        on repeat syncs. Swallows backend/auth errors so a flaky connection
        never breaks the Known Issues panel — callers can check
        ``fetched_count``/``new_outcomes`` to see whether anything came in.
        """
        try:
            reports: list[PlayerCrashReport] = self._teams.list_player_crashes(project_uuid)
        except (BackendAPIError, NotAuthenticatedError):
            return PlayerCrashSyncResult(fetched_count=0, new_outcomes=[])

        outcomes = []
        for report in reports:
            if self._sync_log.is_ingested(project_id, report.id):
                continue
            title = f"{report.error_type}: {report.message}".strip(": ")[:MAX_TITLE_CHARS]
            signature = debug_signature(report.error_type, None)
            outcome = self._regression.note_issue(
                project_id,
                SOURCE_PLAYER,
                signature,
                title or report.error_type,
                category="Player-reported",
            )
            self._sync_log.mark_ingested(project_id, report.id)
            outcomes.append(outcome)
            self._notify_outcome(project_uuid, outcome)
        return PlayerCrashSyncResult(fetched_count=len(reports), new_outcomes=outcomes)

    def _notify_outcome(self, project_uuid: str, outcome: RegressionOutcome) -> None:
        """Best-effort: a brand-new issue or a regression of a resolved one
        notifies whoever's relevant; a repeat of an already-open issue is
        quiet (nothing new to say)."""
        if outcome.match is None:
            event_kind = "known_issue_opened"
            title = f"New issue reported by a player: {outcome.issue.title}"
        elif outcome.match.issue.status == "resolved":
            event_kind = "known_issue_regression"
            title = f"Possible regression reported by a player: {outcome.issue.title}"
        else:
            return
        self._teams.notify_relevant_members_for_project_event(
            project_uuid,
            event_kind,
            title,
            "Reported by a real player of the shipped game.",
            subject_type="known_issue",
            subject_id=str(outcome.issue.id),
        )
