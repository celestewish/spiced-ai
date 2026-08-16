"""Sidebar navigation icons: skeuomorphic Frutiger Aqua glyphs painted on top
of a QSS-styled 44x44 gel orb (see ``ui.theme``'s ``#NavButton``/
``#NavButtonSettings`` rules).

This closes the gap the previous session's icons deliberately left open: the
14 real nav glyphs now use the same layered-glass language as the rest of
the Frutiger Aqua shell (``ui.widgets.mascot_logo`` is the other hand-painted
precedent for this look) instead of flat single-tone strokes. See
``docs/icons.md`` for the full recipe (gradient stop conventions, highlight
placement, shadow treatment, the high-contrast fallback rule) this module
implements -- read that first if you're adding a 15th icon.

Every glyph is still driven by exactly one base color per state (idle/
active), resolved via ``NavOrbButton.set_glyph_colors`` from
``ui.theme.resolve_palette`` -- the gradient/highlight/shadow layers are all
derived procedurally from that single hex (via ``QColor.lighter``/
``.darker``), not a hardcoded second palette, so accessibility palette swaps
(including colorblind-safe) still just work. High-contrast mode renders a
flat, opaque silhouette instead (no gradient/gloss/shadow layers) -- see
``_paint_body``/``_paint_accent`` -- matching ``ui.theme``'s documented rule
that high-contrast drops the glass aesthetic everywhere else in the app.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QPushButton, QWidget

from spiced.ui.effects.splash import attach_splash

_BOX = 24.0  # local drawing coordinate space -- always 24x24, then scaled

# Glossy Orb Recipe token (docs/icons.md): highlight sits at ~32%/28% into
# the shape's bounding box, faking a light source above and to the left.
_HIGHLIGHT_X = 0.32
_HIGHLIGHT_Y = 0.28
_SHADOW_OFFSET = QPointF(0.0, 1.3)


def _pen(color: QColor, width: float = 2.1) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _glass_gradient(rect: QRectF, base: QColor) -> QRadialGradient:
    """The Glossy Orb Recipe, applied to an icon shape instead of button
    chrome: light top-left, saturated base at mid, deep shade bottom-right."""
    cx = rect.left() + rect.width() * _HIGHLIGHT_X
    cy = rect.top() + rect.height() * _HIGHLIGHT_Y
    radius = max(rect.width(), rect.height()) * 0.85
    gradient = QRadialGradient(cx, cy, radius)
    gradient.setColorAt(0.0, base.lighter(185))
    gradient.setColorAt(0.55, base)
    gradient.setColorAt(1.0, base.darker(165))
    return gradient


def _paint_body(p: QPainter, path: QPainterPath, base: QColor, high_contrast: bool) -> None:
    """A primary filled shape: soft drop shadow, glass-gradient fill, a
    darker bevel rim, and a translucent glass highlight cap over the top
    ~40% -- the full skeuomorphic treatment for an icon's main silhouette."""
    if high_contrast:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(base))
        p.drawPath(path)
        return

    p.save()
    p.translate(_SHADOW_OFFSET)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(20, 20, 30, 70))
    p.drawPath(path)
    p.restore()

    rect = path.boundingRect()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_glass_gradient(rect, base)))
    p.drawPath(path)

    p.setPen(QPen(base.darker(170), 1.1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)

    p.save()
    p.setClipPath(path)
    highlight_bottom = rect.top() + rect.height() * 0.42
    highlight = QLinearGradient(rect.left(), rect.top(), rect.left(), highlight_bottom)
    highlight.setColorAt(0.0, QColor(255, 255, 255, 190))
    highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(highlight))
    p.drawRect(QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.42))
    p.restore()


def _paint_accent(p: QPainter, path: QPainterPath, base: QColor, high_contrast: bool) -> None:
    """A secondary filled detail (door, liquid level, handle disc, bead) --
    no shadow/highlight of its own, just a recessed-looking gradient patch
    and a thin rim, so it reads as set into the body rather than floating
    above it."""
    if high_contrast:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(base.darker(130)))
        p.drawPath(path)
        return

    rect = path.boundingRect()
    gradient = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
    gradient.setColorAt(0.0, base.darker(115))
    gradient.setColorAt(1.0, base.darker(150))
    p.setPen(QPen(base.darker(180), 0.9))
    p.setBrush(QBrush(gradient))
    p.drawPath(path)


def _accent_pen(base: QColor, high_contrast: bool, width: float = 2.1) -> QPen:
    """Pen for thin non-filled details (handles, teeth, arcs) -- a shade
    darker than the body so they read as engraved rather than painted flat,
    except under high-contrast where full-strength color wins for legibility."""
    return _pen(base if high_contrast else base.darker(135), width)


def _dashboard(p: QPainter, c: QColor, hc: bool) -> None:  # glass house
    body = QPainterPath()
    body.moveTo(4, 12)
    body.lineTo(12, 5)
    body.lineTo(20, 12)
    body.lineTo(18, 12)
    body.lineTo(18, 19)
    body.lineTo(6, 19)
    body.lineTo(6, 12)
    body.closeSubpath()
    _paint_body(p, body, c, hc)

    door = QPainterPath()
    door.addRoundedRect(QRectF(10.5, 13, 3, 6), 0.6, 0.6)
    _paint_accent(p, door, c, hc)


def _projects(p: QPainter, c: QColor, hc: bool) -> None:  # glass folder
    path = QPainterPath()
    path.moveTo(4, 8)
    path.lineTo(9, 8)
    path.lineTo(11, 10)
    path.lineTo(20, 10)
    path.lineTo(20, 18)
    path.lineTo(4, 18)
    path.closeSubpath()
    _paint_body(p, path, c, hc)


def _debugging(p: QPainter, c: QColor, hc: bool) -> None:  # magnifying glass lens
    lens = QPainterPath()
    lens.addEllipse(QRectF(4, 4, 11, 11))
    _paint_body(p, lens, c, hc)
    p.setPen(_accent_pen(c, hc, 2.4))
    p.drawLine(QPointF(13, 13), QPointF(20, 20))


def _testing(p: QPainter, c: QColor, hc: bool) -> None:  # beaker + liquid
    body = QPainterPath()
    body.moveTo(9, 4)
    body.lineTo(9, 10)
    body.lineTo(4, 19)
    body.lineTo(20, 19)
    body.lineTo(15, 10)
    body.lineTo(15, 4)
    body.closeSubpath()
    _paint_body(p, body, c, hc)

    liquid = QPainterPath()
    liquid.moveTo(6.5, 15.5)
    liquid.lineTo(17.5, 15.5)
    liquid.lineTo(19.4, 18.6)
    liquid.lineTo(4.6, 18.6)
    liquid.closeSubpath()
    if hc:
        _paint_accent(p, liquid, c, hc)
    else:
        rect = liquid.boundingRect()
        gradient = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        gradient.setColorAt(0.0, QColor("#FFC876"))
        gradient.setColorAt(1.0, QColor("#C97E1A"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(gradient))
        p.drawPath(liquid)

    p.setPen(_accent_pen(c, hc))
    p.drawLine(QPointF(7.5, 4), QPointF(16.5, 4))
    p.drawLine(QPointF(6.5, 15.5), QPointF(17.5, 15.5))


def _feedback(p: QPainter, c: QColor, hc: bool) -> None:  # chat bubble + beads
    bubble = QPainterPath()
    bubble.addRoundedRect(QRectF(4, 5, 16, 11), 4, 4)
    tail = QPainterPath()
    tail.moveTo(9, 15.5)
    tail.lineTo(7, 20)
    tail.lineTo(12, 15.5)
    tail.closeSubpath()
    combined = bubble.united(tail)
    _paint_body(p, combined, c, hc)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(c if hc else c.lighter(140)))
    for dx in (8.5, 12, 15.5):
        p.drawEllipse(QPointF(dx, 10.5), 1.15, 1.15)


def _marketing(p: QPainter, c: QColor, hc: bool) -> None:  # megaphone
    body = QPainterPath()
    body.moveTo(4, 13)
    body.lineTo(4, 9)
    body.lineTo(14, 5)
    body.lineTo(14, 17)
    body.closeSubpath()
    _paint_body(p, body, c, hc)

    p.setPen(_accent_pen(c, hc))
    p.drawLine(QPointF(14, 6), QPointF(20, 4))
    p.drawLine(QPointF(14, 16), QPointF(20, 18))
    p.drawLine(QPointF(7, 13), QPointF(8, 19))


def _business(p: QPainter, c: QColor, hc: bool) -> None:  # briefcase
    body = QPainterPath()
    body.addRoundedRect(QRectF(4, 9, 16, 11), 2, 2)
    _paint_body(p, body, c, hc)

    handle = QPainterPath()
    handle.addRoundedRect(QRectF(9, 6, 6, 4), 1, 1)
    _paint_accent(p, handle, c, hc)

    p.setPen(_accent_pen(c, hc, 1.4))
    p.drawLine(QPointF(4, 13), QPointF(20, 13))


def _art(p: QPainter, c: QColor, hc: bool) -> None:  # paintbrush
    handle = QPainterPath()
    handle.moveTo(15.2, 3.4)
    handle.lineTo(19.6, 7.8)
    handle.lineTo(11.6, 15.8)
    handle.lineTo(8.9, 13.1)
    handle.closeSubpath()
    _paint_body(p, handle, c, hc)

    ferrule = QPainterPath()
    ferrule.moveTo(9.9, 14.1)
    ferrule.lineTo(12.6, 16.8)
    ferrule.lineTo(10.6, 18.4)
    ferrule.lineTo(8.3, 16.1)
    ferrule.closeSubpath()
    _paint_accent(p, ferrule, c, hc)

    bristles = QPainterPath()
    bristles.moveTo(8.3, 16.1)
    bristles.lineTo(10.6, 18.4)
    bristles.lineTo(5.5, 20.3)
    bristles.lineTo(4.2, 19.0)
    bristles.closeSubpath()
    if hc:
        _paint_accent(p, bristles, c, hc)
    else:
        rect = bristles.boundingRect()
        gradient = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        gradient.setColorAt(0.0, QColor("#FFB347"))
        gradient.setColorAt(1.0, QColor("#C97E1A"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(gradient))
        p.drawPath(bristles)


def _audio(p: QPainter, c: QColor, hc: bool) -> None:  # speaker + sound waves
    body = QPainterPath()
    body.moveTo(4, 10)
    body.lineTo(8, 10)
    body.lineTo(13, 5)
    body.lineTo(13, 19)
    body.lineTo(8, 14)
    body.lineTo(4, 14)
    body.closeSubpath()
    _paint_body(p, body, c, hc)

    p.setPen(_accent_pen(c, hc))
    p.drawArc(QRectF(14, 7, 8, 10), -60 * 16, 120 * 16)


def _animation(p: QPainter, c: QColor, hc: bool) -> None:  # play triangle + motion arc
    body = QPainterPath()
    body.moveTo(8, 5)
    body.lineTo(8, 19)
    body.lineTo(19, 12)
    body.closeSubpath()
    _paint_body(p, body, c, hc)

    p.setPen(_accent_pen(c, hc))
    p.drawArc(QRectF(2, 2, 20, 20), 200 * 16, 60 * 16)


def _shaders_vfx(p: QPainter, c: QColor, hc: bool) -> None:  # sparkle
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
    _paint_body(p, path, c, hc)


def _team(p: QPainter, c: QColor, hc: bool) -> None:  # two overlapping avatars
    back = QPainterPath()
    back.addEllipse(QRectF(10, 7, 10, 10))
    _paint_body(p, back, c, hc)

    front = QPainterPath()
    front.addEllipse(QRectF(4, 7, 10, 10))
    _paint_body(p, front, c, hc)


def _roadmap(p: QPainter, c: QColor, hc: bool) -> None:  # flagged path
    p.setPen(_accent_pen(c, hc))
    p.drawLine(QPointF(6, 20), QPointF(6, 5))

    flag = QPainterPath()
    flag.moveTo(6, 5)
    flag.lineTo(15, 5)
    flag.lineTo(12, 9)
    flag.lineTo(15, 13)
    flag.lineTo(6, 13)
    flag.closeSubpath()
    _paint_body(p, flag, c, hc)


def _settings(p: QPainter, c: QColor, hc: bool) -> None:  # gear
    ring = QPainterPath()
    ring.addEllipse(QRectF(6.5, 6.5, 11, 11))
    ring.addEllipse(QRectF(9.7, 9.7, 4.6, 4.6))
    ring.setFillRule(Qt.FillRule.OddEvenFill)
    _paint_body(p, ring, c, hc)

    p.setPen(_accent_pen(c, hc, 2.0))
    p.save()
    p.translate(12, 12)
    for i in range(8):
        p.save()
        p.rotate(45 * i)
        p.drawLine(QPointF(0, -9.4), QPointF(0, -6.9))
        p.restore()
    p.restore()


_GLYPHS: dict[str, Callable[[QPainter, QColor, bool], None]] = {
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
        self._high_contrast = False
        attach_splash(self)

    def set_glyph_colors(
        self, idle_hex: str, active_hex: str, *, high_contrast: bool = False
    ) -> None:
        """Called from ui.main_window whenever the app's accessibility
        palette (re)resolves, so the glyph tint -- and, via
        ``high_contrast``, the whole rendering style -- always matches the
        currently active theme. See ui.theme.resolve_palette."""
        self._idle_color = QColor(idle_hex)
        self._active_color = QColor(active_hex)
        self._high_contrast = high_contrast
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
        draw(painter, color, self._high_contrast)
