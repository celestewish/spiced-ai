"""Shared motion helpers for ``ui.effects``.

``reduced_motion`` is the single source every animation added under
``ui.effects`` (and the widgets that use them) checks before starting. It's
backed by the same ``accessibility_reduce_motion_enabled()`` setting
Settings' "Reduce motion" toggle already persists (see
``ui.screens.settings``) -- before this module existed, that toggle was a
documented no-op (``ui.theme``'s module docstring, and the comment on
Settings' own checkbox). Every consumer added under ``ui.effects`` is what
makes it real; this module doesn't change the toggle's own storage.

``Ticker`` is a single shared ``QTimer`` any number of decorative elements
in one scene can subscribe to, so e.g. a background with orbs, waves, and
wind streaks costs one OS timer total rather than one per element.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QObject, QTimer, Signal


class _AccessibilityAware(Protocol):
    def accessibility_reduce_motion_enabled(self) -> bool: ...


def reduced_motion(services: _AccessibilityAware | None) -> bool:
    """True if animations should skip straight to their end state.

    ``services`` is duck-typed rather than importing
    ``spiced.app.services.Services`` -- ``ui.effects`` is meant to stay a
    leaf module that UI screens/widgets import from, not the other way
    around. ``services=None`` (e.g. a widget built in a narrow unit test
    with nothing wired up) is treated as "reduce motion": the safe default.
    """
    if services is None:
        return True
    return bool(services.accessibility_reduce_motion_enabled())


_active_services: _AccessibilityAware | None = None


def set_active_services(services: _AccessibilityAware | None) -> None:
    """Register the app's live ``Services`` instance for effects that can't
    easily thread ``services`` through their own constructor -- ``PillButton``
    in particular, built at around a hundred call sites across every screen,
    where adding a required parameter would mean touching all of them.
    Effects built with ``services`` already on hand (e.g. ``NotificationBell``)
    should keep passing it explicitly instead of relying on this.

    Call once, from ``MainWindow.__init__`` right after ``Services`` exists.
    """
    global _active_services
    _active_services = services


def current_reduced_motion() -> bool:
    """``reduced_motion()`` against whatever was last registered via
    ``set_active_services``. Defaults to the same safe "reduce motion"
    answer ``reduced_motion(None)`` gives if nothing has been registered
    yet -- e.g. a widget built in a unit test that never calls it."""
    return reduced_motion(_active_services)


class Ticker(QObject):
    """One shared ``QTimer`` every ``ui.effects`` animation can subscribe to.

    Construct one per top-level animated scene (not one per decorative
    element within it) and connect to ``tick`` instead of starting a new
    ``QTimer`` per orb/wave/streak.
    """

    tick = Signal()

    def __init__(self, interval_ms: int = 16, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def is_active(self) -> bool:
        return self._timer.isActive()
