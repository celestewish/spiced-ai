"""Sidebar navigation icons: simple two-stroke line glyphs painted on top of
a QSS-styled 44x44 gel orb (see ``ui.theme``'s ``#NavButton``/
``#NavButtonSettings`` rules).

Scope-down, documented: the design handoff's Icon Pack describes fully
skeuomorphic, multi-gradient icon art -- that's for a dedicated reference
screen that doesn't exist as a real Spiced page. Fourteen real nav items
(vs. the handoff's six) need clear, recognizable glyphs at 44px more than
they need hand-illustrated shading, so these are single-tone rounded-stroke
line icons instead. They still respect the accessibility palette: each
button's glyph color is set explicitly via ``NavOrbButton.set_glyph_colors``
(driven by ``ui.theme.resolve_palette``, not hardcoded), unlike
``ui.widgets.mascot_logo``'s fixed brand colors.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QPushButton, QWidget

from spiced.ui.effects.splash import attach_splash

_BOX = 24.0  # local drawing coordinate space -- always 24x24, then scaled


def _pen(color: QColor, width: float = 2.1) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _dashboard(p: QPainter, c: QColor) -> None:  # house
    p.setPen(_pen(c))
    p.drawLine(QPointF(4, 12), QPointF(12, 5))
    p.drawLine(QPointF(12, 5), QPointF(20, 12))
    p.drawLine(QPointF(6, 10), QPointF(6, 19))
    p.drawLine(QPointF(6, 19), QPointF(18, 19))
    p.drawLine(QPointF(18, 19), QPointF(18, 10))
    p.drawRect(QRectF(10.5, 13, 3, 6))


def _projects(p: QPainter, c: QColor) -> None:  # stacked folder
    p.setPen(_pen(c))
    path = QPainterPath()
    path.moveTo(4, 8)
    path.lineTo(9, 8)
    path.lineTo(11, 10)
    path.lineTo(20, 10)
    path.lineTo(20, 18)
    path.lineTo(4, 18)
    path.closeSubpath()
    p.drawPath(path)


def _debugging(p: QPainter, c: QColor) -> None:  # magnifying glass
    p.setPen(_pen(c))
    p.drawEllipse(QRectF(4, 4, 11, 11))
    p.drawLine(QPointF(13, 13), QPointF(20, 20))


def _testing(p: QPainter, c: QColor) -> None:  # beaker
    p.setPen(_pen(c))
    path = QPainterPath()
    path.moveTo(9, 4)
    path.lineTo(9, 10)
    path.lineTo(4, 19)
    path.lineTo(20, 19)
    path.lineTo(15, 10)
    path.lineTo(15, 4)
    p.drawPath(path)
    p.drawLine(QPointF(7.5, 4), QPointF(16.5, 4))
    p.drawLine(QPointF(6.5, 15.5), QPointF(17.5, 15.5))


def _feedback(p: QPainter, c: QColor) -> None:  # chat bubble + 3 dots
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(4, 5, 16, 11), 4, 4)
    path = QPainterPath()
    path.moveTo(9, 16)
    path.lineTo(7, 20)
    path.lineTo(12, 16)
    p.drawPath(path)
    p.setPen(_pen(c, 2.6))
    for dx in (8.5, 12, 15.5):
        p.drawPoint(QPointF(dx, 10.5))


def _marketing(p: QPainter, c: QColor) -> None:  # megaphone
    p.setPen(_pen(c))
    path = QPainterPath()
    path.moveTo(4, 13)
    path.lineTo(4, 9)
    path.lineTo(14, 5)
    path.lineTo(14, 17)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(14, 6), QPointF(20, 4))
    p.drawLine(QPointF(14, 16), QPointF(20, 18))
    p.drawLine(QPointF(7, 13), QPointF(8, 19))


def _business(p: QPainter, c: QColor) -> None:  # briefcase
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(4, 9, 16, 11), 2, 2)
    p.drawLine(QPointF(4, 13), QPointF(20, 13))
    p.drawRoundedRect(QRectF(9, 6, 6, 4), 1, 1)


def _art(p: QPainter, c: QColor) -> None:  # paintbrush
    p.setPen(_pen(c))
    p.drawLine(QPointF(6, 18), QPointF(15, 9))
    p.drawEllipse(QRectF(13, 4, 7, 7))
    p.drawLine(QPointF(6, 18), QPointF(4, 20))


def _audio(p: QPainter, c: QColor) -> None:  # speaker + sound waves
    p.setPen(_pen(c))
    path = QPainterPath()
    path.moveTo(4, 10)
    path.lineTo(8, 10)
    path.lineTo(13, 5)
    path.lineTo(13, 19)
    path.lineTo(8, 14)
    path.lineTo(4, 14)
    path.closeSubpath()
    p.drawPath(path)
    p.drawArc(QRectF(14, 7, 8, 10), -60 * 16, 120 * 16)


def _animation(p: QPainter, c: QColor) -> None:  # play triangle + motion arc
    p.setPen(_pen(c))
    path = QPainterPath()
    path.moveTo(8, 5)
    path.lineTo(8, 19)
    path.lineTo(19, 12)
    path.closeSubpath()
    p.drawPath(path)
    p.drawArc(QRectF(2, 2, 20, 20), 200 * 16, 60 * 16)


def _shaders_vfx(p: QPainter, c: QColor) -> None:  # sparkle
    p.setPen(_pen(c))
    path = QPainterPath()
    path.moveTo(12, 3)
    path.lineTo(15, 10)
    path.lineTo(21, 12)
    path.lineTo(15, 14)
    path.lineTo(12, 21)
    path.lineTo(9, 14)
    path.lineTo(3, 12)
    path.lineTo(9, 10)
    path.closeSubpath()
    p.drawPath(path)


def _team(p: QPainter, c: QColor) -> None:  # two overlapping avatars
    p.setPen(_pen(c))
    p.drawEllipse(QRectF(4, 7, 10, 10))
    p.drawEllipse(QRectF(10, 7, 10, 10))


def _roadmap(p: QPainter, c: QColor) -> None:  # flagged path
    p.setPen(_pen(c))
    p.drawLine(QPointF(6, 20), QPointF(6, 5))
    path = QPainterPath()
    path.moveTo(6, 5)
    path.lineTo(15, 5)
    path.lineTo(12, 9)
    path.lineTo(15, 13)
    path.lineTo(6, 13)
    p.drawPath(path)


def _settings(p: QPainter, c: QColor) -> None:  # gear
    p.setPen(_pen(c))
    p.drawEllipse(QRectF(8, 8, 8, 8))
    p.drawEllipse(QRectF(10.5, 10.5, 3, 3))
    p.save()
    p.translate(12, 12)
    for i in range(8):
        p.save()
        p.rotate(45 * i)
        p.drawLine(QPointF(0, -9), QPointF(0, -6.5))
        p.restore()
    p.restore()


_GLYPHS: dict[str, Callable[[QPainter, QColor], None]] = {
    "dashboard": _dashboard,
    "projects": _projects,
    "debugging": _debugging,
    "testing": _testing,
    "feedback": _feedback,
    "marketing": _marketing,
    "business": _business,
    "art": _art,
    "audio": _audio,
    "animation": _animation,
    "shaders_vfx": _shaders_vfx,
    "team": _team,
    "roadmap": _roadmap,
    "settings": _settings,
}


class NavOrbButton(QPushButton):
    """A checkable 44x44 sidebar nav icon: QSS paints the gel-orb background
    (``#NavButton``/``#NavButtonSettings`` in ui.theme, so it still responds
    to accessibility palette swaps), this class paints the glyph on top."""

    def __init__(
        self,
        kind: str,
        tooltip: str,
        *,
        settings: bool = False,
        size: int = 44,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("NavButtonSettings" if settings else "NavButton")
        self.setCheckable(True)
        self.setFixedSize(size, size)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._kind = kind
        self._idle_color = QColor("#FFFFFF")
        self._active_color = QColor("#0A2A35")
        attach_splash(self)

    def set_glyph_colors(self, idle_hex: str, active_hex: str) -> None:
        """Called from ui.main_window whenever the app's accessibility
        palette (re)resolves, so the glyph tint always matches the
        currently active theme -- see ui.theme.resolve_palette."""
        self._idle_color = QColor(idle_hex)
        self._active_color = QColor(active_hex)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt override)
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self._active_color if self.isChecked() else self._idle_color
        side = min(self.width(), self.height())
        scale = (side * 0.58) / _BOX
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(scale, scale)
        painter.translate(-_BOX / 2, -_BOX / 2)
        draw = _GLYPHS.get(self._kind, _settings)
        draw(painter, color)
