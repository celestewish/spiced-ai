"""A QPushButton that always paints a genuinely round, antialiased shape.

``water_fill=True`` opts a button into an indeterminate "water level"
loading indicator (``set_loading``) -- see that method's docstring for why
this is deliberately indeterminate rather than a real percentage.

Qt's QSS ``border-radius`` on ``QPushButton`` is not reliably honored by
this app's Qt/PySide6 build: reproduced with a minimal, isolated repro
(a single ``QPushButton`` with nothing but ``background`` / ``border`` /
``border-radius`` set, no other widgets involved) that the corners come out
perfectly square regardless of radius value (999px or an exact
height-matched value), checked state, or whether ``border`` is ``none`` vs
an explicit transparent border -- confirmed with pixel-level sampling of
the rendered corner, not just a visual read (a naive screenshot crop
resized with bilinear/bicubic interpolation blurs square corners just
enough to *look* rounded, which is a trap -- always re-check with a
nearest-neighbor zoom or direct pixel sampling).

Since the QSS property itself can't be trusted here, this widget paints the
rounded shape itself instead of asking Qt's stylesheet cascade for it:

1. Render the button normally and *unclipped* via
   ``style().drawControl(QStyle.CE_PushButton, ...)``, so the normal
   QSS-driven background/text/hover/checked/disabled/Ghost styling from
   ``ui.theme`` still applies untouched. (Clipping a rounded path *during*
   this draw -- the first approach tried here -- makes Qt's own border
   renderer glitch on bordered/Ghost buttons: with no working radius to
   round the corners into, it draws the four border edges as if arcs would
   join them, and clipping mid-draw leaves those edges disconnected and
   fragmented instead of forming a closed rectangle. Rendering unclipped
   avoids that failure mode entirely.)
2. Punch the four corners outside a rounded-rect path back to transparent
   (``CompositionMode_Clear``), which is what actually makes the shape
   round.
3. Because step 2 also chops off whatever fragment of the (already broken)
   native border fell in those corners, the "Ghost" (outline) variant needs
   its border redrawn as a single continuous stroke along the *same*
   rounded-rect path. Its color is sampled from the pixels Qt already
   rendered in step 1 (a single fixed probe point just inside the left
   edge) rather than hardcoded, so it stays correct across
   hover/disabled/accessibility-palette states without this widget needing
   to know the theme's actual color values.

   Detecting a border's *presence* from pixels alone turned out to be too
   unreliable to trust: Fusion's own bevel/gradient shading near a flat
   button's edge is sometimes different enough from its center fill color
   to look like a border by any reasonable per-pixel color-distance
   threshold, so a generic pixel-based "is there a border here" scan
   produced false positives (observed as a solid-black-filled tab button in
   testing) on plain, borderless pills. ``ghost`` is already an explicit,
   reliable signal for "this button has a border" -- every bordered
   PillButton in this codebase is constructed with it -- so border drawing
   is gated on that flag instead of inferred.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton, QWidget

from spiced.ui.effects.motion import Ticker, current_reduced_motion
from spiced.ui.effects.splash import attach_splash

# Border stroke width to draw for ghost=True buttons, matching the
# `QPushButton#Ghost { border: 2px solid ... }` rule in ui.theme.
_GHOST_BORDER_WIDTH = 2

# Water-fill loading indicator (icons.md's aqua accent ramp).
_FILL_DEEP = QColor("#0A7EA8")
_FILL_BRIGHT = QColor("#BDF3FF")
_FILL_TICK_MS = 16
_FILL_PERIOD_SECONDS = 1.6
_FILL_MIN_FRAC = 0.15
_FILL_MAX_FRAC = 0.85
_FILL_STATIC_FRAC = 0.4  # reduced-motion resting level while loading


class PillButton(QPushButton):
    """Drop-in QPushButton replacement, always visually rounded.

    ``radius`` defaults to half the button's own height (a full pill/stadium
    shape, or a circle for a square button); pass an explicit pixel value
    for a smaller, card-style corner radius instead (e.g. ``ToolListItem``'s
    14px). Pass ``ghost=True`` instead of ``setObjectName("Ghost")`` for the
    outlined variant.

    Every instance gets a water-drop click splash for free (see
    ``ui.effects.splash``) -- skipped automatically when Reduce Motion is on.
    """

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        radius: float | None = None,
        ghost: bool = False,
        water_fill: bool = False,
    ) -> None:
        super().__init__(text, parent)
        self._fixed_radius = radius
        self._ghost = ghost
        if ghost:
            self.setObjectName("Ghost")
        attach_splash(self)

        self._water_fill_enabled = water_fill
        self._loading = False
        self._fill_elapsed = 0.0
        self._fill_ticker: Ticker | None = None
        if water_fill:
            self._fill_ticker = Ticker(_FILL_TICK_MS, self)
            self._fill_ticker.tick.connect(self._on_fill_tick)

    def set_loading(self, active: bool) -> None:
        """Show (or clear) an indeterminate water-level loading fill.

        Deliberately indeterminate, not a real percentage: this button has
        no per-stage progress signal to report from (a single AI call is
        one opaque request/response), and Spiced never fakes a number it
        doesn't actually have. A future screen whose worker does emit real
        incremental progress should get its own real percentage API when
        that lands, not this one repurposed to fake it.

        No-op if this instance wasn't constructed with ``water_fill=True``.
        """
        if not self._water_fill_enabled or self._fill_ticker is None:
            return
        self._loading = active
        if active and not current_reduced_motion():
            self._fill_elapsed = 0.0
            self._fill_ticker.start()
        else:
            self._fill_ticker.stop()
            self._fill_elapsed = 0.0
        self.update()

    def _on_fill_tick(self) -> None:
        self._fill_elapsed += _FILL_TICK_MS / 1000.0
        self.update()

    def _fill_fraction(self) -> float:
        """0..1 height fraction for the current frame -- a smooth raised-
        cosine breathing motion between _FILL_MIN_FRAC/_FILL_MAX_FRAC while
        the ticker is running, or a fixed resting level when it isn't
        (Reduce Motion, or between ticks right after set_loading(True))."""
        if self._fill_ticker is None or not self._fill_ticker.is_active():
            return _FILL_STATIC_FRAC
        swing = (1 - math.cos(2 * math.pi * self._fill_elapsed / _FILL_PERIOD_SECONDS)) / 2
        return _FILL_MIN_FRAC + (_FILL_MAX_FRAC - _FILL_MIN_FRAC) * swing

    def paintEvent(self, event: QPaintEvent) -> None:
        if self.width() <= 0 or self.height() <= 0:
            super().paintEvent(event)
            return

        radius = self._fixed_radius if self._fixed_radius is not None else self.height() / 2

        dpr = self.devicePixelRatioF()
        buffer = QPixmap(self.size() * dpr)
        buffer.setDevicePixelRatio(dpr)
        buffer.fill(Qt.transparent)
        buffer_painter = QPainter(buffer)
        buffer_painter.setRenderHint(QPainter.Antialiasing)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        self.style().drawControl(QStyle.CE_PushButton, option, buffer_painter, self)
        buffer_painter.end()

        border_color = self._sample_ghost_border_color(buffer) if self._ghost else None

        buffer_painter = QPainter(buffer)
        buffer_painter.setRenderHint(QPainter.Antialiasing)
        logical_rect = QRectF(0, 0, self.width(), self.height())
        full_rect = QPainterPath()
        full_rect.addRect(logical_rect)
        rounded_rect = QPainterPath()
        rounded_rect.addRoundedRect(logical_rect, radius, radius)
        corners = full_rect.subtracted(rounded_rect)
        buffer_painter.setCompositionMode(QPainter.CompositionMode_Clear)
        buffer_painter.fillPath(corners, Qt.transparent)
        buffer_painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        if self._water_fill_enabled and self._loading:
            fill_frac = self._fill_fraction()
            fill_height = logical_rect.height() * fill_frac
            fill_rect = QRectF(
                0, logical_rect.height() - fill_height, logical_rect.width(), fill_height
            )
            gradient = QLinearGradient(0, fill_rect.top(), 0, fill_rect.bottom())
            gradient.setColorAt(0.0, _FILL_BRIGHT)
            gradient.setColorAt(1.0, _FILL_DEEP)
            buffer_painter.save()
            buffer_painter.setClipPath(rounded_rect)
            buffer_painter.setOpacity(0.55)
            buffer_painter.fillRect(fill_rect, gradient)
            buffer_painter.restore()

        if border_color is not None:
            inset = _GHOST_BORDER_WIDTH / 2.0
            stroke_rect = logical_rect.adjusted(inset, inset, -inset, -inset)
            stroke_radius = max(radius - inset, 0)
            stroke_path = QPainterPath()
            stroke_path.addRoundedRect(stroke_rect, stroke_radius, stroke_radius)
            buffer_painter.setPen(QPen(border_color, _GHOST_BORDER_WIDTH))
            buffer_painter.drawPath(stroke_path)
        buffer_painter.end()

        widget_painter = QPainter(self)
        widget_painter.setRenderHint(QPainter.Antialiasing)
        widget_painter.drawPixmap(0, 0, buffer)

    @staticmethod
    def _sample_ghost_border_color(buffer: QPixmap) -> QColor | None:
        """Read the border color Qt already rendered, just inside the left edge.

        A single fixed probe point at vertical-center, 1 logical px in from
        the edge -- close enough to the border to be unambiguous, but not the
        very edge pixel (which can be a partial-coverage antialiasing
        blend). Only called for ``ghost=True`` buttons, where a border is
        already known to exist, so there's no "is this actually a border"
        judgment call to get wrong.

        ``toImage()`` addresses raw physical pixels, not the logical,
        devicePixelRatio-adjusted ones ``buffer`` itself reports -- on a
        scaled display the probe point has to be scaled up to match, or it
        samples an antialiased edge pixel instead of solid border color.
        """
        image = buffer.toImage()
        height = image.height()
        if height <= 0 or image.width() <= 1:
            return None
        dpr = buffer.devicePixelRatio() or 1.0
        probe_x = max(1, round(dpr))
        return QColor(image.pixel(probe_x, height // 2))
