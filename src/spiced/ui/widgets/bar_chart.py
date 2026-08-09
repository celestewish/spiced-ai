"""Frame-rate bar chart (Automated Testing's Performance tab) -- one bar per
sampled location, colored aqua normally and coral for any location a fps
spike was flagged at (core.performance_parser.PerformanceSpike). Real data
only: fed from the same ParsedPerformance the text review already used,
never fabricated.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

_NORMAL_TOP = QColor("#7fe7ff")
_NORMAL_BOTTOM = QColor("#0a7ea8")
_SPIKE_TOP = QColor("#ffb1a3")
_SPIKE_BOTTOM = QColor("#e2604f")
_EMPTY_TEXT_COLOR = QColor(255, 255, 255, 150)


class FrameRateBarChart(QWidget):
    """``set_data`` takes a list of ``(location_label, fps, is_spike)``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(170)
        self._bars: list[tuple[str, float, bool]] = []

    def set_data(self, bars: list[tuple[str, float, bool]]) -> None:
        self._bars = bars
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt override), ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self._bars:
            painter.setPen(_EMPTY_TEXT_COLOR)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Analyze performance data to see a frame-rate chart here.",
            )
            return

        margin_side = 10
        margin_bottom = 24
        margin_top = 10
        width = self.width()
        height = self.height()
        count = len(self._bars)
        gap = 10.0
        available = max(0.0, width - margin_side * 2 - gap * (count - 1))
        bar_width = max(10.0, available / count)
        max_fps = max((fps for _label, fps, _spike in self._bars), default=1.0) or 1.0
        chart_height = height - margin_top - margin_bottom

        painter.setPen(Qt.PenStyle.NoPen)
        x = float(margin_side)
        font = painter.font()
        font.setPointSizeF(max(font.pointSizeF() - 2, 7))
        painter.setFont(font)
        for label, fps, is_spike in self._bars:
            bar_h = max(4.0, (fps / max_fps) * chart_height)
            rect = QRectF(x, margin_top + chart_height - bar_h, bar_width, bar_h)
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            top, bottom = (_SPIKE_TOP, _SPIKE_BOTTOM) if is_spike else (_NORMAL_TOP, _NORMAL_BOTTOM)
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(1.0, bottom)
            painter.setBrush(gradient)
            painter.drawRoundedRect(rect, 4, 4)

            painter.setPen(QColor(70, 60, 90, 220))
            label_rect = QRectF(x - gap / 2, margin_top + chart_height + 4, bar_width + gap, 18)
            elided = label if len(label) <= 12 else label[:11] + "…"
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter, elided)
            painter.setPen(Qt.PenStyle.NoPen)
            x += bar_width + gap
