"""PillButton's indeterminate water-fill loading indicator (Frutiger Aero
pass 5/5).

Deliberately indeterminate, not a real percentage -- see set_loading's own
docstring for why. No display is available in this environment, so this
uses Qt's offscreen platform plugin, matching the pattern used by the other
widget tests.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.ui.effects import motion  # noqa: E402
from spiced.ui.widgets.pill_button import PillButton  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakeServices:
    def __init__(self, *, reduce_motion: bool) -> None:
        self._reduce_motion = reduce_motion

    def accessibility_reduce_motion_enabled(self) -> bool:
        return self._reduce_motion


def teardown_function() -> None:
    motion.set_active_services(None)  # don't leak state between tests


def test_water_fill_disabled_by_default():
    button = PillButton("Plain")
    assert button._water_fill_enabled is False
    assert button._fill_ticker is None


def test_set_loading_is_a_no_op_without_water_fill_enabled():
    button = PillButton("Plain")
    button.set_loading(True)  # must not raise
    assert button._loading is False


def test_set_loading_starts_the_ticker_when_motion_is_not_reduced():
    motion.set_active_services(_FakeServices(reduce_motion=False))
    button = PillButton("Regenerate docs", water_fill=True)
    button.resize(160, 32)

    button.set_loading(True)

    assert button._loading is True
    assert button._fill_ticker.is_active() is True


def test_set_loading_false_stops_the_ticker_and_resets():
    motion.set_active_services(_FakeServices(reduce_motion=False))
    button = PillButton("Regenerate docs", water_fill=True)
    button.set_loading(True)

    button.set_loading(False)

    assert button._loading is False
    assert button._fill_ticker.is_active() is False
    assert button._fill_elapsed == 0.0


def test_reduced_motion_keeps_a_static_fill_instead_of_animating():
    motion.set_active_services(_FakeServices(reduce_motion=True))
    button = PillButton("Regenerate docs", water_fill=True)
    button.resize(160, 32)

    button.set_loading(True)

    assert button._loading is True
    assert button._fill_ticker.is_active() is False
    assert button._fill_fraction() > 0  # still visibly "busy", just not moving


def test_no_active_services_defaults_to_static_fill():
    # motion.current_reduced_motion() defaults to True with nothing
    # registered -- same safe default the splash effect uses.
    button = PillButton("Regenerate docs", water_fill=True)
    button.set_loading(True)
    assert button._fill_ticker.is_active() is False


def test_fill_fraction_oscillates_within_bounds_while_animating():
    motion.set_active_services(_FakeServices(reduce_motion=False))
    button = PillButton("Regenerate docs", water_fill=True)
    button.set_loading(True)

    fractions = []
    for _ in range(200):
        button._on_fill_tick()
        fractions.append(button._fill_fraction())

    assert min(fractions) >= 0.15
    assert max(fractions) <= 0.85
    # Actually moves rather than sitting flat.
    assert max(fractions) - min(fractions) > 0.3


def test_paints_without_error_while_loading():
    motion.set_active_services(_FakeServices(reduce_motion=False))
    button = PillButton("Regenerate docs", water_fill=True, ghost=True)
    button.resize(160, 32)
    button.set_loading(True)
    for _ in range(5):
        button._on_fill_tick()
    button.repaint()


def test_paints_without_error_after_loading_clears():
    motion.set_active_services(_FakeServices(reduce_motion=False))
    button = PillButton("Regenerate docs", water_fill=True)
    button.resize(160, 32)
    button.set_loading(True)
    button.set_loading(False)
    button.repaint()
