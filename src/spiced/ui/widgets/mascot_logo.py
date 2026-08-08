"""Mascot logo: the "tropical saffron flower" brand mark from the Frutiger
Aqua design handoff -- six rotated gel petals around a gold center disc,
drawn entirely with ``QPainter``. No image asset, per the handoff's own note
that it's "built entirely from CSS gradients/shapes... recreate as an SVG or
component" -- this is that component, and (see ``ui.theme``'s module
docstring) the first custom-painted widget in the codebase, kept small and
isolated rather than a pattern used elsewhere.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPaintEvent, QRadialGradient
from PySide6.QtWidgets import QWidget

_PETAL_COUNT = 6
_PETAL_TOP = QColor("#FFF6E8")
_PETAL_MID = QColor("#FF9D54")
_PETAL_BOTTOM = QColor("#E2604F")
_CENTER_LIGHT = QColor("#FFE9A8")
_CENTER_DEEP = QColor("#D2721F")


class MascotLogo(QWidget):
    """Fixed-size flower mark, meant to sit beside the "Spiced" wordmark."""

    def __init__(self, size: int = 34, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt override), ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)

        side = min(self.width(), self.height())
        petal_w = side * 0.30
        petal_h = side * 0.62
        petal_rect = QRectF(-petal_w / 2, -side * 0.47, petal_w, petal_h)

        petal_gradient = QLinearGradient(petal_rect.topLeft(), petal_rect.bottomLeft())
        petal_gradient.setColorAt(0.0, _PETAL_TOP)
        petal_gradient.setColorAt(0.55, _PETAL_MID)
        petal_gradient.setColorAt(1.0, _PETAL_BOTTOM)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(petal_gradient)

        for i in range(_PETAL_COUNT):
            painter.save()
            painter.rotate(360 / _PETAL_COUNT * i)
            painter.drawRoundedRect(petal_rect, petal_w / 2, petal_w / 2)
            painter.restore()

        center_radius = side * 0.22
        center_gradient = QRadialGradient(
            -center_radius * 0.3, -center_radius * 0.3, center_radius * 1.4
        )
        center_gradient.setColorAt(0.0, _CENTER_LIGHT)
        center_gradient.setColorAt(1.0, _CENTER_DEEP)
        painter.setBrush(center_gradient)
        painter.drawEllipse(
            QRectF(-center_radius, -center_radius, center_radius * 2, center_radius * 2)
        )
