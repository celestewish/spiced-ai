"""Notification Center digest-cadence bucketing tests (Phase K, section 9
part 1, Core tier).

Pure-function tests only -- no Qt, no real timers, no network. See
``ui.notification_center`` for the QTimer-based poller that wraps
``bucket_by_cadence`` around a periodic backend fetch; that wiring is
exercised for import-cleanliness only (see test_team_ui_imports.py), since
there's no display available in this environment.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from spiced.backend_client.api_client import Notification, NotificationPreference
from spiced.core.notification_center import bucket_by_cadence, delivery_for_event_kind

_NOW = datetime(2026, 8, 5, 12, 0, 0)


def _notification(event_kind: str, note_id: str = "n1") -> Notification:
    return Notification(
        id=note_id,
        team_id="team-1",
        recipient_user_id="u1",
        event_kind=event_kind,
        title="Title",
        body="Body",
        subject_type=None,
        subject_id=None,
        created_at="2026-08-05T12:00:00Z",
        read_at=None,
    )


def _pref(event_kind: str, delivery: str) -> NotificationPreference:
    return NotificationPreference(
        id=f"p-{event_kind}", team_id="team-1", user_id="u1", event_kind=event_kind,
        enabled=True, created_at="2026-08-05T00:00:00Z", delivery=delivery,
    )


# --- delivery_for_event_kind -------------------------------------------------


def test_delivery_defaults_to_realtime_when_no_preference_saved():
    assert delivery_for_event_kind("build_failed", []) == "realtime"


def test_delivery_uses_saved_preference():
    prefs = [_pref("build_failed", "hourly")]
    assert delivery_for_event_kind("build_failed", prefs) == "hourly"
    assert delivery_for_event_kind("comment_posted", prefs) == "realtime"


# --- bucket_by_cadence --------------------------------------------------------


def test_realtime_notification_always_surfaces_immediately():
    notifications = [_notification("comment_posted")]
    result = bucket_by_cadence(
        notifications, [], now=_NOW, last_hourly_flush=_NOW, last_daily_flush=_NOW
    )
    assert result.to_surface == notifications
    assert result.hourly_held == []
    assert result.daily_held == []


def test_hourly_notification_is_held_until_the_bucket_is_due():
    notifications = [_notification("build_failed")]
    prefs = [_pref("build_failed", "hourly")]

    # Flushed 10 minutes ago -- not due yet, held.
    result = bucket_by_cadence(
        notifications, prefs, now=_NOW,
        last_hourly_flush=_NOW - timedelta(minutes=10), last_daily_flush=None,
    )
    assert result.to_surface == []
    assert result.hourly_held == notifications
    assert result.hourly_flushed is False


def test_hourly_notification_surfaces_once_an_hour_has_passed():
    notifications = [_notification("build_failed")]
    prefs = [_pref("build_failed", "hourly")]

    result = bucket_by_cadence(
        notifications, prefs, now=_NOW,
        last_hourly_flush=_NOW - timedelta(hours=1, minutes=1), last_daily_flush=None,
    )
    assert result.to_surface == notifications
    assert result.hourly_held == []
    assert result.hourly_flushed is True


def test_hourly_notification_surfaces_when_never_flushed_before():
    notifications = [_notification("build_failed")]
    prefs = [_pref("build_failed", "hourly")]

    result = bucket_by_cadence(
        notifications, prefs, now=_NOW, last_hourly_flush=None, last_daily_flush=None
    )
    assert result.to_surface == notifications
    assert result.hourly_flushed is True


def test_daily_notification_is_held_until_a_day_has_passed():
    notifications = [_notification("known_issue_opened")]
    prefs = [_pref("known_issue_opened", "daily")]

    held = bucket_by_cadence(
        notifications, prefs, now=_NOW,
        last_hourly_flush=None, last_daily_flush=_NOW - timedelta(hours=23),
    )
    assert held.to_surface == []
    assert held.daily_held == notifications
    assert held.daily_flushed is False

    due = bucket_by_cadence(
        notifications, prefs, now=_NOW,
        last_hourly_flush=None, last_daily_flush=_NOW - timedelta(days=1, minutes=1),
    )
    assert due.to_surface == notifications
    assert due.daily_held == []
    assert due.daily_flushed is True


def test_mixed_cadences_are_bucketed_independently():
    realtime_note = _notification("comment_posted", "n1")
    hourly_note = _notification("build_failed", "n2")
    daily_note = _notification("known_issue_opened", "n3")
    prefs = [_pref("build_failed", "hourly"), _pref("known_issue_opened", "daily")]

    result = bucket_by_cadence(
        [realtime_note, hourly_note, daily_note],
        prefs,
        now=_NOW,
        last_hourly_flush=_NOW,  # just flushed -- not due
        last_daily_flush=_NOW,  # just flushed -- not due
    )
    assert result.to_surface == [realtime_note]
    assert result.hourly_held == [hourly_note]
    assert result.daily_held == [daily_note]


def test_flushed_flags_are_false_when_nothing_of_that_cadence_is_present():
    """No hourly/daily notifications at all this pass -- even though the
    bucket is "due" by elapsed time, there's nothing to flush, so the
    caller shouldn't bother advancing its stored flush timestamp."""
    notifications = [_notification("comment_posted")]
    result = bucket_by_cadence(
        notifications, [], now=_NOW, last_hourly_flush=None, last_daily_flush=None
    )
    assert result.hourly_flushed is False
    assert result.daily_flushed is False


def test_empty_notifications_bucket_cleanly():
    result = bucket_by_cadence([], [], now=_NOW, last_hourly_flush=None, last_daily_flush=None)
    assert result.to_surface == []
    assert result.hourly_held == []
    assert result.daily_held == []
    assert result.hourly_flushed is False
    assert result.daily_flushed is False
