"""TutorialOverlay: step advancement, skip-at-any-step, target/cutout
geometry, and the structural guarantee that motivated this module's whole
design -- no QGraphicsEffect, no per-frame ticking (Unity Alpha Readiness
Spec's Priority 1 fixed exactly this class of bug elsewhere; this overlay
must be structurally unable to reintroduce it).

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching the pattern used by the other widget tests.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsEffect, QWidget  # noqa: E402

from spiced.ui.tutorial.tutorial_overlay import TutorialOverlay, TutorialStep  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakeServices:
    def __init__(self, *, high_contrast: bool = False, colorblind_safe: bool = False) -> None:
        self._high_contrast = high_contrast
        self._colorblind_safe = colorblind_safe

    def accessibility_high_contrast_enabled(self) -> bool:
        return self._high_contrast

    def accessibility_colorblind_safe_enabled(self) -> bool:
        return self._colorblind_safe


def _window_with_target():
    window = QWidget()
    window.resize(800, 600)
    target = QWidget(window)
    target.setGeometry(100, 100, 120, 40)
    window.show()
    target.show()
    return window, target


def test_start_shows_the_overlay_and_the_first_step():
    window, target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices())
    steps = [
        TutorialStep(title="First", body="First body", target=lambda: target),
        TutorialStep(title="Second", body="Second body", target=lambda: target),
    ]

    overlay.start(steps, on_finished=lambda skipped: None)

    assert overlay.isVisible() is True
    assert overlay._title_label.text() == "First"
    assert overlay._body_label.text() == "First body"


def test_next_button_advances_through_steps():
    window, target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices())
    steps = [
        TutorialStep(title="First", body="", target=lambda: target),
        TutorialStep(title="Second", body="", target=lambda: target),
    ]
    overlay.start(steps, on_finished=lambda skipped: None)

    overlay._advance()

    assert overlay._title_label.text() == "Second"


def test_advancing_past_the_last_step_finishes_not_skipped():
    window, target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices())
    steps = [TutorialStep(title="Only", body="", target=lambda: target)]
    finished = []
    overlay.start(steps, on_finished=lambda skipped: finished.append(skipped))

    overlay._advance()  # runs past the only step

    assert finished == [False]
    assert overlay.isVisible() is False


def test_skip_finishes_with_skipped_true_at_any_step():
    window, target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices())
    steps = [
        TutorialStep(title="First", body="", target=lambda: target),
        TutorialStep(title="Second", body="", target=lambda: target),
    ]
    finished = []
    overlay.start(steps, on_finished=lambda skipped: finished.append(skipped))
    overlay._advance()  # now on step 2 of 2

    overlay._skip_btn.click()

    assert finished == [True]
    assert overlay.isVisible() is False


def test_on_enter_callback_runs_when_its_step_is_shown():
    window, target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices())
    calls = []
    steps = [
        TutorialStep(title="First", body="", target=lambda: target, on_enter=lambda: calls.append(1)),
        TutorialStep(title="Second", body="", target=lambda: target, on_enter=lambda: calls.append(2)),
    ]

    overlay.start(steps, on_finished=lambda skipped: None)
    assert calls == [1]
    overlay._advance()
    assert calls == [1, 2]


def test_auto_advance_signal_hides_next_and_fires_on_signal():
    window, target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices())

    from PySide6.QtCore import Signal

    class _WithSignal(QWidget):
        done = Signal()

    signaler = _WithSignal()
    steps = [
        TutorialStep(title="Waits", body="", target=lambda: target, auto_advance_signal=signaler.done),
        TutorialStep(title="Next step", body="", target=lambda: target),
    ]
    overlay.start(steps, on_finished=lambda skipped: None)

    assert overlay._next_btn.isVisible() is False

    signaler.done.emit()

    assert overlay._title_label.text() == "Next step"


def test_target_resolved_fresh_each_time_not_cached():
    window, target = _window_with_target()
    other_target = QWidget(window)
    other_target.setGeometry(300, 300, 80, 30)
    other_target.show()

    calls = []

    def _resolve():
        calls.append(1)
        return target if len(calls) == 1 else other_target

    overlay = TutorialOverlay(window, _FakeServices())
    steps = [TutorialStep(title="One", body="", target=_resolve)]
    overlay.start(steps, on_finished=lambda skipped: None)
    # .repaint() is a documented no-op under the offscreen QPA platform (see
    # tools/profile_effects.py's module docstring) -- .render() drives the
    # real paintEvent synchronously, so two calls means two real paints.
    overlay.render(_blank_pixmap(window))
    overlay.render(_blank_pixmap(window))

    # target() is called again on each paint, not memoized from start().
    assert len(calls) >= 2


def _blank_pixmap(window):
    from PySide6.QtGui import QPixmap

    return QPixmap(window.size())


def test_paints_without_error_and_positions_the_callout_within_bounds():
    window, target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices())
    steps = [TutorialStep(title="One", body="A body long enough to wrap.", target=lambda: target)]
    overlay.start(steps, on_finished=lambda skipped: None)

    overlay.render(_blank_pixmap(window))  # must not raise

    assert overlay._callout.isVisible() is True
    assert overlay._callout.x() >= 0
    assert overlay._callout.y() >= 0


def test_paints_without_error_when_target_resolves_to_none():
    window, _target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices())
    steps = [TutorialStep(title="Gone", body="", target=lambda: None)]
    overlay.start(steps, on_finished=lambda skipped: None)

    overlay.render(_blank_pixmap(window))  # must not raise -- falls back to centered

    assert overlay._callout.isVisible() is True


def test_high_contrast_scrim_is_flat_and_fully_opaque():
    window, target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices(high_contrast=True))
    overlay._steps = [TutorialStep(title="x", body="", target=lambda: target)]

    color = overlay._scrim_color()

    assert color.alpha() == 255


def test_normal_scrim_is_translucent_and_derived_from_the_sidebar_palette():
    from spiced.ui import theme

    window, target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices(high_contrast=False))
    overlay._steps = [TutorialStep(title="x", body="", target=lambda: target)]

    color = overlay._scrim_color()

    assert 0 < color.alpha() < 255
    expected = theme.resolve_palette(high_contrast=False, colorblind_safe=False)["SIDEBAR"]
    assert color.name() == expected.lower()


def test_no_qgraphics_effect_or_timer_anywhere_in_the_overlay():
    # The structural guarantee this whole module exists to provide -- see
    # its module docstring. A QGraphicsEffect or a QTimer/Ticker here would
    # reintroduce the exact class of framerate bug Priority 1 just fixed.
    window, target = _window_with_target()
    overlay = TutorialOverlay(window, _FakeServices())
    steps = [TutorialStep(title="One", body="", target=lambda: target)]
    overlay.start(steps, on_finished=lambda skipped: None)

    assert overlay.graphicsEffect() is None
    assert overlay._callout.graphicsEffect() is None
    assert overlay.findChildren(QGraphicsEffect) == []
    assert overlay.findChildren(QTimer) == []
