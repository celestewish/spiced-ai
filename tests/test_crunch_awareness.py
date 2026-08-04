"""Tests for core.crunch_awareness: threshold detection over crafted
session-summary timestamps, plus a hard structural check that this module
never touches TeamService/BackendClient — Crunch-Pattern Awareness data must
stay 100% local, even for team-linked projects (plan's explicit judgment
call #5).

Late-night detection is inherently a *local clock* concept (see the
module's own docstring: stored timestamps are UTC, converted to local time
before applying the threshold), so these tests build inputs from a local
wall-clock time and convert to the UTC storage string themselves — that
keeps the late-night assertions correct regardless of which timezone the
machine running the tests happens to be in.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime

from spiced.core import crunch_awareness
from spiced.core.crunch_awareness import (
    LATE_NIGHT_END_HOUR,
    LONG_SESSION_HOURS,
    SUSTAINED_SESSION_COUNT,
    detect_crunch_pattern,
)
from spiced.storage.session_summaries import SessionSummary

NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)  # a fixed reference point


def _local_to_utc_string(local_naive: datetime) -> str:
    """Convert a *local* wall-clock time into the UTC storage string
    core.crunch_awareness would see in session_summaries.ended_at/started_at."""
    return local_naive.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _summary(idx: int, started_local: datetime, ended_local: datetime) -> SessionSummary:
    started_at = _local_to_utc_string(started_local)
    ended_at = _local_to_utc_string(ended_local)
    return SessionSummary(
        id=idx,
        project_id=1,
        started_at=started_at,
        ended_at=ended_at,
        tested_summary=None,
        fixed_summary=None,
        open_summary=None,
        ai_summary=None,
        synced_to_team=False,
        created_at=ended_at,
    )


# --- Threshold detection ------------------------------------------------------


def test_no_qualifying_sessions_produces_no_message():
    summaries = [
        _summary(1, datetime(2026, 8, 1, 14, 0, 0), datetime(2026, 8, 1, 16, 0, 0)),
        _summary(2, datetime(2026, 8, 2, 9, 0, 0), datetime(2026, 8, 2, 11, 0, 0)),
    ]
    result = detect_crunch_pattern(summaries, now=NOW)
    assert result.flagged_sessions == []
    assert result.sustained is False
    assert result.message is None


def test_a_single_late_night_is_not_sustained():
    summaries = [_summary(1, datetime(2026, 8, 2, 20, 0, 0), datetime(2026, 8, 2, 23, 30, 0))]
    result = detect_crunch_pattern(summaries, now=NOW)
    assert len(result.flagged_sessions) == 1
    assert result.flagged_sessions[0].late_night is True
    assert result.sustained is False
    assert result.message is None


def test_three_late_nights_in_the_trailing_week_is_sustained_and_neutral():
    """The spec's own example tone: 'You've logged 5 late nights this week.'
    Deterministic count, no guilt/gamification language."""
    summaries = [
        _summary(1, datetime(2026, 7, 30, 20, 0, 0), datetime(2026, 7, 30, 23, 30, 0)),
        _summary(2, datetime(2026, 7, 31, 20, 0, 0), datetime(2026, 7, 31, 23, 15, 0)),
        # Session 3 ran past midnight local time.
        _summary(3, datetime(2026, 8, 1, 21, 0, 0), datetime(2026, 8, 2, 0, 10, 0)),
    ]
    result = detect_crunch_pattern(summaries, now=NOW)
    assert len(result.flagged_sessions) == SUSTAINED_SESSION_COUNT
    assert result.sustained is True
    assert result.message is not None
    assert "3" in result.message
    assert "no action needed" in result.message
    # Tone check: nothing guilt-tripping or gamified.
    for banned_word in ("should", "must", "bad", "streak", "score", "!"):
        assert banned_word not in result.message.lower()


def test_long_daytime_sessions_also_count_toward_the_pattern():
    summaries = [
        _summary(1, datetime(2026, 7, 30, 9, 0, 0), datetime(2026, 7, 30, 14, 0, 0)),  # 5h
        _summary(2, datetime(2026, 7, 31, 9, 0, 0), datetime(2026, 7, 31, 13, 30, 0)),  # 4.5h
        _summary(3, datetime(2026, 8, 1, 9, 0, 0), datetime(2026, 8, 1, 13, 0, 0)),  # exactly 4h
    ]
    result = detect_crunch_pattern(summaries, now=NOW)
    assert all(s.long_session and not s.late_night for s in result.flagged_sessions)
    assert result.sustained is True


def test_sessions_outside_the_trailing_window_are_ignored():
    old = [
        _summary(1, datetime(2026, 7, 1, 20, 0, 0), datetime(2026, 7, 1, 23, 30, 0)),
        _summary(2, datetime(2026, 7, 2, 20, 0, 0), datetime(2026, 7, 2, 23, 30, 0)),
        _summary(3, datetime(2026, 7, 3, 20, 0, 0), datetime(2026, 7, 3, 23, 30, 0)),
    ]
    result = detect_crunch_pattern(old, now=NOW)
    assert result.flagged_sessions == []
    assert result.message is None


def test_boundary_case_ended_exactly_at_late_night_hour_counts():
    """A session ending exactly at the late-night cutoff (local time) should
    be flagged; one minute earlier should not (absent a long duration)."""
    assert LATE_NIGHT_END_HOUR == 23
    at_boundary = _summary(
        1, datetime(2026, 8, 2, 21, 0, 0), datetime(2026, 8, 2, 23, 0, 0)
    )
    just_before = _summary(
        2, datetime(2026, 8, 2, 21, 0, 0), datetime(2026, 8, 2, 22, 59, 0)
    )

    boundary_result = detect_crunch_pattern([at_boundary], now=NOW)
    before_result = detect_crunch_pattern([just_before], now=NOW)

    assert boundary_result.flagged_sessions[0].late_night is True
    assert before_result.flagged_sessions == []


def test_boundary_case_exactly_at_long_session_hours_counts():
    assert LONG_SESSION_HOURS == 4.0
    at_boundary = _summary(1, datetime(2026, 8, 2, 9, 0, 0), datetime(2026, 8, 2, 13, 0, 0))
    just_under = _summary(2, datetime(2026, 8, 2, 9, 0, 0), datetime(2026, 8, 2, 12, 59, 0))

    boundary_result = detect_crunch_pattern([at_boundary], now=NOW)
    under_result = detect_crunch_pattern([just_under], now=NOW)

    assert boundary_result.flagged_sessions[0].long_session is True
    assert under_result.flagged_sessions == []


def test_malformed_timestamp_is_skipped_not_raised():
    summaries = [
        SessionSummary(
            id=1,
            project_id=1,
            started_at="not-a-timestamp",
            ended_at="also-not-a-timestamp",
            tested_summary=None,
            fixed_summary=None,
            open_summary=None,
            ai_summary=None,
            synced_to_team=False,
            created_at="also-not-a-timestamp",
        )
    ]
    result = detect_crunch_pattern(summaries, now=NOW)
    assert result.flagged_sessions == []


# --- Hard privacy boundary: never touches TeamService/BackendClient ---------


def test_module_never_imports_team_service_or_backend_client():
    """Structural guarantee, not just a docstring claim: parse the actual
    import statements of core.crunch_awareness (ignoring prose in the
    module's own docstring, which legitimately *names* these two things
    while explaining the boundary) and confirm neither is ever imported."""
    source = inspect.getsource(crunch_awareness)
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden = ("team_service", "backend_client")
    for module_name in imported_modules:
        for term in forbidden:
            assert term not in module_name, (
                f"crunch_awareness.py must never import {module_name}"
            )


def test_detect_crunch_pattern_never_calls_team_service_or_backend_client(monkeypatch):
    """Runtime spy: even if some future refactor tried to sneak a call in,
    calling either would raise here."""
    import spiced.backend_client.api_client as api_client_module
    import spiced.core.team_service as team_service_module

    def _boom(*args, **kwargs):
        raise AssertionError("crunch_awareness must never call TeamService/BackendClient")

    monkeypatch.setattr(team_service_module.TeamService, "post_session_summary", _boom)
    monkeypatch.setattr(team_service_module.TeamService, "find_team_for_project", _boom)
    monkeypatch.setattr(api_client_module.BackendClient, "post_session_summary", _boom)

    summaries = [
        _summary(1, datetime(2026, 7, 30, 20, 0, 0), datetime(2026, 7, 30, 23, 30, 0)),
        _summary(2, datetime(2026, 7, 31, 20, 0, 0), datetime(2026, 7, 31, 23, 15, 0)),
        _summary(3, datetime(2026, 8, 1, 21, 0, 0), datetime(2026, 8, 2, 0, 10, 0)),
    ]
    result = detect_crunch_pattern(summaries, now=NOW)
    assert result.sustained is True  # ran to completion without tripping the spies
