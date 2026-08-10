"""Regression tests for PillButton/PillLabel rendering on scaled ("HiDPI")
displays.

Both widgets paint into an offscreen QPixmap buffer. Before this fix the
buffer was sized in logical pixels with no devicePixelRatio tagged on it, so
on any scaled display (125%/150%/200% Windows scaling, or a Retina Mac —
very common, not an edge case) every button and pill in the app rendered
soft instead of crisp. See the module docstrings on pill_button.py /
pill_label.py for the full story.

No display is available in this environment, so this uses Qt's offscreen
platform plugin (set before the first PySide6 import) to instantiate real
widgets headlessly, matching the pattern used by the other widget tests
(e.g. test_source_link_widget.py).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.ui.widgets.pill_button import PillButton  # noqa: E402
from spiced.ui.widgets.pill_label import PillLabel  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _dpr_tagged_pixmap(color: QColor, logical_size: int, dpr: float) -> QPixmap:
    pixmap = QPixmap(round(logical_size * dpr), round(logical_size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(color)
    return pixmap


def test_border_color_sample_is_correct_at_1x():
    buffer = _dpr_tagged_pixmap(QColor("#123456"), logical_size=40, dpr=1.0)
    sampled = PillButton._sample_ghost_border_color(buffer)
    assert sampled is not None
    assert sampled.name() == QColor("#123456").name()


def test_border_color_sample_is_correct_at_2x():
    # A pixmap tagged devicePixelRatio=2 has a physical backing store twice
    # the logical size; the probe must scale with it or it lands on an
    # unrelated (or out-of-bounds-adjacent) physical pixel.
    buffer = _dpr_tagged_pixmap(QColor("#abcdef"), logical_size=40, dpr=2.0)
    sampled = PillButton._sample_ghost_border_color(buffer)
    assert sampled is not None
    assert sampled.name() == QColor("#abcdef").name()


def test_border_color_sample_handles_fractional_scaling():
    buffer = _dpr_tagged_pixmap(QColor("#ff0080"), logical_size=40, dpr=1.5)
    sampled = PillButton._sample_ghost_border_color(buffer)
    assert sampled is not None
    assert sampled.name() == QColor("#ff0080").name()


def test_border_color_sample_returns_none_for_degenerate_buffer():
    empty = QPixmap(0, 0)
    assert PillButton._sample_ghost_border_color(empty) is None


def test_pill_button_paints_without_error_on_a_scaled_display(monkeypatch):
    widget = PillButton("Click me", ghost=True)
    widget.resize(80, 32)
    monkeypatch.setattr(widget, "devicePixelRatioF", lambda: 2.0)
    widget.repaint()  # exercises paintEvent's offscreen-buffer path at dpr=2


def test_pill_button_paints_without_error_with_fixed_radius(monkeypatch):
    widget = PillButton("OK", radius=6)
    widget.resize(60, 28)
    monkeypatch.setattr(widget, "devicePixelRatioF", lambda: 1.5)
    widget.repaint()


def test_pill_label_paints_without_error_on_a_scaled_display(monkeypatch):
    widget = PillLabel("Ready for Playtesters")
    widget.resize(180, 24)
    monkeypatch.setattr(widget, "devicePixelRatioF", lambda: 2.0)
    widget.repaint()
