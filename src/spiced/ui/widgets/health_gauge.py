"""Build Health gauge: a conic-gradient ring, per the Frutiger Aqua design
handoff's Dashboard spec.

Deliberately shows the readiness *label* text in its center, not a numeric
percentage -- the ring's fill is a coarse, 4-bucket visual (see
``core.dashboard.HEALTH_FILL_BY_LABEL``), not a precise computed score.
Spiced's Build Health Score is documented as "persistent, non-gamified"; a
granular number in a gauge like this would read as exactly the kind of score
that principle exists to avoid, even though the ring shape itself is a nice,
faithful piece of the visual design.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QConicalGradient, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

_RING_WIDTH = 14
_TRACK_COLOR = QColor(255, 255, 255, 60)
_RING_START = QColor("#bdf3ff")
_RING_MID = QColor("#22b8d6")
_RING_END = QColor("#0a7ea8")
_DISC_TOP = QColor(20, 14, 50, 235)
_DISC_BOTTOM = QColor(60, 20, 70, 215)


class HealthGauge(QWidget):
    """Fixed-size circular gauge -- ``set_value`` takes 0-100 (a coarse fill
    fraction, see module docstring) and a short label shown at its center."""

    def __init__(self, size: int = 120, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._fill_pct = 0
        self._label = "—"

    def set_value(self, fill_pct: int, label: str) -> None:
        self._fill_pct = max(0, min(100, fill_pct))
        self._label = label
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt override), ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        ring_rect = QRectF(
            _RING_WIDTH / 2, _RING_WIDTH / 2, side - _RING_WIDTH, side - _RING_WIDTH
        )

        inset = _RING_WIDTH
        pen = painter.pen()
        pen.setWidth(_RING_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        pen.setColor(_TRACK_COLOR)
        painter.setPen(pen)
        painter.drawArc(ring_rect, 0, 360 * 16)

        if self._fill_pct > 0:
            gradient = QConicalGradient(ring_rect.center(), 90)
            gradient.setColorAt(0.0, _RING_START)
            gradient.setColorAt(0.55, _RING_MID)
            gradient.setColorAt(1.0, _RING_END)
            pen.setBrush(gradient)
            painter.setPen(pen)
            span = int(360 * 16 * (self._fill_pct / 100))
            painter.drawArc(ring_rect, 90 * 16, -span)

        painter.setPen(Qt.PenStyle.NoPen)
        disc_rect = QRectF(inset, inset, side - inset * 2, side - inset * 2)
        painter.setBrush(_DISC_BOTTOM)
        painter.drawEllipse(disc_rect)

        painter.setPen(QColor(255, 255, 255))
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(font.pointSizeF() - 1, 8))
        painter.setFont(font)
        text_rect = disc_rect.adjusted(4, -6, -4, 6)
        text_flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
        painter.drawText(text_rect, text_flags, self._label)
