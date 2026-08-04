"""Crunch-Pattern Awareness use-case (Phase F, section 6, Core tier).

Reuses Phase B's ``session_summaries`` table history (``started_at``/
``ended_at`` per project) — no new capture mechanism. Pure, deterministic,
100% local: no AI call, no network, and — this is the important part — no
import of ``core.team_service`` or anything under ``backend_client``
anywhere in this file. Session timing is personal wellbeing data; per the
plan's explicit judgment call #5, it must never be synced to the team
backend, even for team-linked projects. Keeping this module free of any
import from those two places is a structural guarantee, not just a
docstring claim — see ``tests/test_crunch_awareness.py`` for a test that
enforces it.

Timestamps stored in ``session_summaries`` are UTC (``core.session_summary.
now_sqlite`` uses ``datetime.now(UTC)``), but "worked past 11pm" is
inherently a local-clock idea, so this module converts to the machine's
local time before applying the thresholds below.

Tone: informational only, per spec's own example ("You've logged 5 late
nights this week") — no action taken, no gamification, no guilt framing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from spiced.storage.session_summaries import SessionSummary

# A session counts as a "late night" if it ended at or after this local hour
# (24h clock), or before this early-morning hour (covers a session that ran
# past midnight). 11pm is late enough to be an unambiguous signal for most
# schedules without flagging every ordinary evening work session; 4am covers
# sessions that started late and ran into the small hours.
LATE_NIGHT_END_HOUR = 23
EARLY_MORNING_END_HOUR = 4

# A session counts as "long" if it ran at least this many hours end-to-end.
# 4 hours is a deliberately generous bar — a solid uninterrupted work block,
# not just "touched the project a few times this afternoon."
LONG_SESSION_HOURS = 4.0

# A pattern is only surfaced once at least this many qualifying sessions land
# within the trailing window below — a single late night is normal; a
# sustained run of them is what this feature exists to gently note.
SUSTAINED_SESSION_COUNT = 3
TRAILING_WINDOW_DAYS = 7

_TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class FlaggedSession:
    summary_id: int
    ended_local: datetime
    duration_hours: float
    late_night: bool
    long_session: bool


@dataclass(frozen=True)
class CrunchPatternResult:
    flagged_sessions: list[FlaggedSession] = field(default_factory=list)
    window_days: int = TRAILING_WINDOW_DAYS

    @property
    def sustained(self) -> bool:
        return len(self.flagged_sessions) >= SUSTAINED_SESSION_COUNT

    @property
    def message(self) -> str | None:
        """A short, neutral, informational note — or None if there's
        nothing worth mentioning. Deliberately factual, no guilt or
        gamification: matches the spec's own example tone."""
        if not self.sustained:
            return None
        count = len(self.flagged_sessions)
        session_word = "session" if count == 1 else "sessions"
        return (
            f"You've logged {count} late or long work {session_word} in the last "
            f"{self.window_days} days. Just a heads-up — no action needed."
        )


def detect_crunch_pattern(
    summaries: list[SessionSummary], *, now: datetime | None = None
) -> CrunchPatternResult:
    """Pure, deterministic, 100% local.

    ``summaries`` is whatever ``SessionSummaryService.history()`` /
    ``SessionSummaryRepository.list_for_project()`` already returns — no new
    query, no new capture mechanism. Never calls out to a network, an AI
    provider, TeamService, or BackendClient.
    """
    reference = now if now is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    window_start = reference - timedelta(days=TRAILING_WINDOW_DAYS)

    flagged: list[FlaggedSession] = []
    for summary in summaries:
        ended = _parse_utc(summary.ended_at)
        if ended is None or ended < window_start:
            continue
        started = _parse_utc(summary.started_at)

        ended_local = ended.astimezone()
        duration_hours = 0.0
        if started is not None and ended >= started:
            duration_hours = (ended - started).total_seconds() / 3600.0

        late_night = (
            ended_local.hour >= LATE_NIGHT_END_HOUR or ended_local.hour < EARLY_MORNING_END_HOUR
        )
        long_session = duration_hours >= LONG_SESSION_HOURS
        if late_night or long_session:
            flagged.append(
                FlaggedSession(
                    summary_id=summary.id,
                    ended_local=ended_local,
                    duration_hours=duration_hours,
                    late_night=late_night,
                    long_session=long_session,
                )
            )

    return CrunchPatternResult(flagged_sessions=flagged)
