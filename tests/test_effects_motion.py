"""ui.effects.motion: reduced_motion(services) and the shared Ticker.

reduced_motion is the single gate every Frutiger Aero animation effect
checks before starting -- see ui/effects/__init__.py's module docstring.
This is the foundational PR of that sequence: no actual animation consumer
exists yet, just the accessor and the shared-timer helper both will use.

No display is available in this environment, so QTimer-based tests use
Qt's offscreen platform plugin, matching the pattern used elsewhere
(e.g. test_progress_trail.py).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.effects.motion import Ticker, reduced_motion  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_reduced_motion_reflects_the_real_accessibility_setting(tmp_path):
    services = Services(db_path=str(tmp_path / "spiced.db"))
    try:
        assert reduced_motion(services) is False  # off by default

        services.set_accessibility_reduce_motion_enabled(True)
        assert reduced_motion(services) is True

        services.set_accessibility_reduce_motion_enabled(False)
        assert reduced_motion(services) is False
    finally:
        services.close()


def test_reduced_motion_defaults_to_true_with_no_services():
    # Safe default for a widget built without one wired up (e.g. a narrow
    # unit test) -- never silently animate when we don't know the setting.
    assert reduced_motion(None) is True


def test_ticker_starts_stopped():
    ticker = Ticker()
    assert ticker.is_active() is False


def test_ticker_start_and_stop_toggle_active_state():
    ticker = Ticker()
    ticker.start()
    assert ticker.is_active() is True
    ticker.stop()
    assert ticker.is_active() is False


def test_ticker_emits_tick_on_a_timeout():
    from PySide6.QtCore import QEventLoop, QTimer

    ticker = Ticker(interval_ms=5)
    received = []
    ticker.tick.connect(lambda: received.append(True))
    ticker.start()

    loop = QEventLoop()
    QTimer.singleShot(50, loop.quit)
    loop.exec()
    ticker.stop()

    assert received
