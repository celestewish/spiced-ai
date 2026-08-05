"""Notification Center: digest-cadence bucketing (Phase K, section 9 part 1,
Core tier).

Pure logic only -- no Qt, no network. See ``ui.notification_center`` for the
QTimer-based poller (mirrors ``ui.build_scheduler``'s QTimer pattern exactly)
that wraps this around a periodic fetch of the backend's unread
notifications for the active project's team.

Per notification-preference (``backend_client.api_client.
NotificationPreference.delivery``), a developer chooses whether an event
kind's notifications surface immediately ("realtime", the default) or are
held and only surfaced in a batch at a fixed cadence ("hourly"/"daily"). The
backend has no concept of "held" -- every unread notification is always
sitting there waiting to be listed (see ``app.routers.notifications.
list_notifications``); the digest behavior lives entirely on the desktop
client's side, in the bucketing decision below, keyed off how long it's been
since this client last "flushed" that cadence's bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from spiced.backend_client.api_client import Notification, NotificationPreference

REALTIME = "realtime"
HOURLY = "hourly"
DAILY = "daily"
DELIVERY_CADENCES = (REALTIME, HOURLY, DAILY)

_HOURLY_INTERVAL = timedelta(hours=1)
_DAILY_INTERVAL = timedelta(days=1)


def delivery_for_event_kind(event_kind: str, preferences: list[NotificationPreference]) -> str:
    """One user's chosen cadence for ``event_kind``, defaulting to
    "realtime" when they've never saved a preference for it -- mirrors
    ``core.notification_routing``'s "absence of a row means the default"
    convention."""
    for pref in preferences:
        if pref.event_kind == event_kind:
            return pref.delivery or REALTIME
    return REALTIME


@dataclass(frozen=True)
class DigestBucketResult:
    """The outcome of one bucketing pass over a user's current unread
    notifications.

    ``hourly_flushed``/``daily_flushed`` tell the caller whether *this* pass
    surfaced a due hourly/daily bucket -- callers should advance their
    stored ``last_hourly_flush``/``last_daily_flush`` to ``now`` whenever the
    corresponding flag is True, so the next bucket doesn't surface again
    immediately.
    """

    to_surface: list[Notification]
    hourly_held: list[Notification]
    daily_held: list[Notification]
    hourly_flushed: bool
    daily_flushed: bool


def bucket_by_cadence(
    notifications: list[Notification],
    preferences: list[NotificationPreference],
    *,
    now: datetime,
    last_hourly_flush: datetime | None,
    last_daily_flush: datetime | None,
) -> DigestBucketResult:
    """Split ``notifications`` into what should surface right now vs. what
    stays held for a later digest, per each notification's event kind's
    configured delivery cadence.

    A "realtime" notification always surfaces immediately. An "hourly" (or
    "daily") one only surfaces once its bucket is due -- ``last_*_flush`` is
    None (never flushed before) or at least an hour (a day) in the past --
    at which point *every* currently-held notification of that cadence
    surfaces together, as one batch, rather than trickling out one at a
    time.
    """
    hourly_due = last_hourly_flush is None or (now - last_hourly_flush) >= _HOURLY_INTERVAL
    daily_due = last_daily_flush is None or (now - last_daily_flush) >= _DAILY_INTERVAL

    to_surface: list[Notification] = []
    hourly_held: list[Notification] = []
    daily_held: list[Notification] = []
    saw_hourly = False
    saw_daily = False

    for notification in notifications:
        cadence = delivery_for_event_kind(notification.event_kind, preferences)
        if cadence == HOURLY:
            saw_hourly = True
            (to_surface if hourly_due else hourly_held).append(notification)
        elif cadence == DAILY:
            saw_daily = True
            (to_surface if daily_due else daily_held).append(notification)
        else:
            to_surface.append(notification)

    return DigestBucketResult(
        to_surface=to_surface,
        hourly_held=hourly_held,
        daily_held=daily_held,
        hourly_flushed=hourly_due and saw_hourly,
        daily_flushed=daily_due and saw_daily,
    )
