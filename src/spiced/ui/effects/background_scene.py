"""Ocean background scene: sunset sky, island, waves, orbs, wind, parallax.

Replaces MainWindow's old static glow-blob paintEvent with a dedicated
background widget sitting behind the top bar / sidebar / workspace /
context-panel row (see ui.main_window). Colors, gradient stops, island
silhouette, and orb/wind-streak seed data are ported directly from the
design prototype (Dashboard.dc.html) rather than approximated.

Two things the prototype didn't have to handle that this widget does:

- **Reduce Motion** (ui.effects.motion.reduced_motion): the single shared
  Ticker never starts, mouse parallax is zeroed, and everything still
  paints once at its resting state -- never a blank background.
- **High-contrast accessibility palette**: an animated, busy scene actively
  works against the point of that palette (see Services.
  accessibility_high_contrast_enabled), so this widget hides itself
  entirely when it's on, letting the plain #Root QSS background (solid
  white in that palette, see ui.theme) show through untouched instead.

One QTimer total, wrapped in ui.effects.motion.Ticker and shared by every
decorative element below (orbs, wind streaks, waves, twinkle stars) -- see
Ticker's own docstring for why that matters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from spiced.ui.effects.motion import Ticker, reduced_motion

# --- Sky -----------------------------------------------------------------

_SKY_STOPS: tuple[tuple[float, str], ...] = (
    (0.0, "#160f38"),
    (0.2, "#3a1361"),
    (0.38, "#7c2f78"),
    (0.54, "#e2604f"),
    (0.66, "#ff9d54"),
    (0.74, "#ffdf8f"),
    (0.8, "#7fe7ff"),
    (0.92, "#22b8d6"),
    (1.0, "#0a7ea8"),
)

# --- Island (viewBox-local units, 400x220 -- see Dashboard.dc.html) ------

_ISLAND_VIEWBOX = (400.0, 220.0)
# Fraction of the widget's own size the island box occupies, and its
# anchor -- matches the prototype's right:6%; bottom:30%; width:340px;
# height:190px at its 1440x900 preview size. The island's pixel size is
# scaled with the window (see _island_rect) rather than kept fixed, so it
# holds a similar relative visual weight from Spiced's 920x600 minimum
# window up through a large one -- the prototype never had to handle a
# resizable window.
_ISLAND_BASELINE_WIDTH = 1440.0
_ISLAND_BASELINE_SIZE = (340.0, 190.0)
_ISLAND_RIGHT_MARGIN_FRAC = 0.06
_ISLAND_BOTTOM_FRAC = 0.30

_ISLAND_SHADOW = QColor("#2a1a4a")
_ISLAND_BACK = QColor("#3a2a5c")
_ISLAND_FRONT = QColor("#4a3670")
_PALM = QColor("#2f6b3f")

# --- Ocean / waves ---------------------------------------------------------

_OCEAN_BAND_FRAC = 0.46  # bottom fraction of the widget the ocean band covers


@dataclass(frozen=True)
class _WaveLayer:
    baseline_frac: float  # 0..1 within the ocean band's own height
    amplitude_frac: float
    color: str
    opacity: float
    # Seconds for the pattern to drift exactly one period -- ported from
    # the prototype's wave-drift animation-duration (18s/26s/34s); sign
    # flips the direction, matching its "reverse" on the middle layer.
    period_seconds: float


_WAVE_LAYERS: tuple[_WaveLayer, ...] = (
    # Opacity is each layer's fill alpha times its own wrapper opacity in
    # the prototype (layer 1 has no wrapper opacity; layers 2/3 do: 0.7,
    # 0.55) -- e.g. layer 2 is rgba(189,243,255,0.3) at wrapper opacity
    # 0.7, so 0.3 * 0.7 = 0.21.
    _WaveLayer(0.5, 0.35, "#7FE7FF", 0.35, 18.0),
    _WaveLayer(0.55, 0.30, "#BDF3FF", 0.21, -26.0),
    _WaveLayer(0.6, 0.25, "#FFFFFF", 0.121, 34.0),
)
_WAVE_PERIOD_FRAC = 0.5  # one full hump+trough cycle spans half the widget's width

# --- Orbs (seeds ported directly from Dashboard.dc.html's ORB_SEEDS) -----


@dataclass(frozen=True)
class _Orb:
    left_frac: float
    top_frac: float
    size: float
    dx: float
    dy: float
    duration_seconds: float
    delay_seconds: float


_ORBS: tuple[_Orb, ...] = (
    _Orb(0.12, 0.60, 26, 16, -26, 9.0, 0.0),
    _Orb(0.24, 0.40, 14, -12, -18, 7.5, 1.2),
    _Orb(0.08, 0.80, 20, 10, -20, 11.0, 0.6),
    _Orb(0.30, 0.72, 10, -8, -14, 6.5, 2.1),
    _Orb(0.18, 0.30, 16, 14, -22, 8.2, 0.9),
    _Orb(0.04, 0.45, 12, 8, -16, 10.0, 1.7),
)

# --- Wind streaks (seeds ported from Dashboard.dc.html's WIND_SEEDS) -----


@dataclass(frozen=True)
class _WindStreak:
    top_frac: float
    duration_seconds: float
    delay_seconds: float


_WIND_STREAKS: tuple[_WindStreak, ...] = (
    _WindStreak(0.15, 12.0, 0.0),
    _WindStreak(0.34, 16.0, 4.0),
    _WindStreak(0.55, 20.0, 8.0),
)
_WIND_STREAK_WIDTH = 120.0

# --- Twinkle stars (positions ported from Dashboard.dc.html) -------------


@dataclass(frozen=True)
class _Star:
    left_frac: float
    top_frac: float
    radius: float
    period_seconds: float
    delay_seconds: float


_STARS: tuple[_Star, ...] = (
    _Star(0.55, 0.12, 2.5, 4.0, 0.0),
    _Star(0.68, 0.22, 1.5, 5.0, 0.6),
    _Star(0.40, 0.07, 2.0, 3.4, 1.1),
)

# 30fps rather than 60fps: this is a decorative, slow-drifting backdrop, not
# something a user tracks frame-by-frame, so halving the steady-state paint
# cost isn't perceptible here the way it would be for e.g. a scrub animation.
# Kept as its own named constant so it's easy to tune/re-measure with
# tools/profile_effects.py.
_TICK_INTERVAL_MS = 33  # ~30fps


class OceanBackgroundWidget(QWidget):
    def __init__(self, services: object | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._elapsed_seconds = 0.0
        self._mouse_norm = QPointF(0.0, 0.0)

        self._ticker = Ticker(_TICK_INTERVAL_MS, self)
        self._ticker.tick.connect(self._on_tick)

        self._island_back, self._island_front = _build_island_paths()

        # Sky/sun/island only depend on size and mouse-parallax offset, not
        # on _elapsed_seconds -- unlike waves/orbs/wind/stars, they're
        # identical from one 16ms tick to the next whenever the mouse hasn't
        # moved (the common case), so they're worth baking into a cached
        # pixmap instead of repainting a 9-stop gradient fill + two more
        # layers from scratch every single tick (see tools/profile_effects.py
        # for the measurement that motivated this).
        self._backdrop_cache: QPixmap | None = None
        self._backdrop_cache_key: tuple | None = None

        # One cached QPainterPath per wave layer (index -> (key, path)),
        # keyed on everything that changes the path's *shape* (size, band
        # geometry) but not its per-tick drift -- rebuilding via
        # _wave_path's Python loop is only worth doing on resize, not on
        # every 16/33ms tick. Drift is applied by translating the painter
        # instead (see _wave_path_cached / _paint_ocean_and_waves).
        self._wave_path_cache: dict[int, tuple[tuple, QPainterPath]] = {}

        # Whether the *window* this widget lives in can currently be seen at
        # all -- minimized, or not the active window (e.g. the user alt-tabbed
        # away). Independent of the accessibility-driven pause below; either
        # one stops the ticker. Assumed visible until MainWindow says
        # otherwise (see set_window_visible), so construction/tests that never
        # call it behave exactly as before.
        self._window_visible = True

        self.refresh_accessibility_state()

    # --- Public API ----------------------------------------------------

    def refresh_accessibility_state(self) -> None:
        """Re-check Reduce Motion / high-contrast and adjust accordingly.

        Call once at construction (done in __init__) and again whenever
        Settings saves an accessibility change (see MainWindow), the same
        way MainWindow._apply_nav_glyph_colors is re-invoked for the
        sidebar's own accessibility-driven repaint.
        """
        high_contrast = bool(
            self._services is not None
            and getattr(self._services, "accessibility_high_contrast_enabled", lambda: False)()
        )
        self.setVisible(not high_contrast)
        self._reduced_motion_or_high_contrast = high_contrast or reduced_motion(self._services)
        self._apply_ticker_state()
        self.update()

    def set_window_visible(self, visible: bool) -> None:
        """Pause/resume the ticker as the containing window is minimized or
        loses/regains being the active window (see MainWindow.changeEvent).

        A minimized or backgrounded window still burns a full 60fps repaint
        cycle otherwise, for a scene nobody can see -- this is on top of,
        not instead of, the reduced-motion/high-contrast checks above.
        """
        if visible == self._window_visible:
            return
        self._window_visible = visible
        self._apply_ticker_state()

    def _apply_ticker_state(self) -> None:
        if self._reduced_motion_or_high_contrast or not self._window_visible:
            self._ticker.stop()
        else:
            self._ticker.start()

    def set_mouse_norm(self, x: float, y: float) -> None:
        """x, y in -1..1 -- see MainWindow.mouseMoveEvent."""
        self._mouse_norm = QPointF(x, y)
        if not reduced_motion(self._services):
            self.update()

    # --- Ticking ---------------------------------------------------------

    def _on_tick(self) -> None:
        self._elapsed_seconds += _TICK_INTERVAL_MS / 1000.0
        self.update()

    # --- Painting ----------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt override)
        if self.width() <= 0 or self.height() <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(event.rect())

        amp = 0.0 if reduced_motion(self._services) else 1.0
        px, py = self._mouse_norm.x() * amp, self._mouse_norm.y() * amp

        painter.drawPixmap(0, 0, self._backdrop_pixmap(px, py))
        self._paint_ocean_and_waves(painter, px, py)
        self._paint_orbs(painter, px, py)
        self._paint_wind_streaks(painter)
        self._paint_stars(painter)

    def _backdrop_pixmap(self, px: float, py: float) -> QPixmap:
        """The cached sky+sun+island layer -- see the cache fields' comment
        in __init__. Rebuilt only when size/parallax/DPR actually change."""
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), round(px, 3), round(py, 3), dpr)
        if self._backdrop_cache is not None and self._backdrop_cache_key == key:
            return self._backdrop_cache

        pixmap = QPixmap(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        cache_painter = QPainter(pixmap)
        cache_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_sky(cache_painter, px, py)
        self._paint_sun(cache_painter, px, py)
        self._paint_island(cache_painter, px, py)
        cache_painter.end()

        self._backdrop_cache = pixmap
        self._backdrop_cache_key = key
        return pixmap

    def _paint_sky(self, painter: QPainter, px: float, py: float) -> None:
        w, h = self.width(), self.height()
        gradient = QLinearGradient(0, 0, 0, h)
        for stop, color in _SKY_STOPS:
            gradient.setColorAt(stop, QColor(color))
        painter.save()
        painter.translate(px * 6, py * 3)
        painter.fillRect(QRectF(-10, -10, w + 20, h + 20), gradient)
        painter.restore()

    def _paint_sun(self, painter: QPainter, px: float, py: float) -> None:
        w = self.width()
        size = 56.0
        cx, cy = w * 0.5, self.height() * 0.02 + size / 2
        gradient = QRadialGradient(cx, cy, size / 2)
        gradient.setColorAt(0.0, QColor("#fff6d8"))
        gradient.setColorAt(0.55, QColor("#ffdf8f"))
        gradient.setColorAt(1.0, QColor(255, 223, 143, 0))
        painter.save()
        painter.translate(px * 6, py * 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(cx, cy), size / 2, size / 2)
        painter.restore()

    def _island_rect(self) -> QRectF:
        scale = _clamp(self.width() / _ISLAND_BASELINE_WIDTH, 0.6, 1.4)
        w = _ISLAND_BASELINE_SIZE[0] * scale
        h = _ISLAND_BASELINE_SIZE[1] * scale
        x = self.width() * (1.0 - _ISLAND_RIGHT_MARGIN_FRAC) - w
        y = self.height() * (1.0 - _ISLAND_BOTTOM_FRAC) - h
        return QRectF(x, y, w, h)

    def _paint_island(self, painter: QPainter, px: float, py: float) -> None:
        rect = self._island_rect()
        sx = rect.width() / _ISLAND_VIEWBOX[0]
        sy = rect.height() / _ISLAND_VIEWBOX[1]

        painter.save()
        painter.translate(px * 12, py * 5)
        painter.translate(rect.x(), rect.y())
        painter.scale(sx, sy)
        painter.setOpacity(0.92)

        painter.setPen(Qt.PenStyle.NoPen)
        shadow = QColor(_ISLAND_SHADOW)
        shadow.setAlphaF(0.35)
        painter.setBrush(shadow)
        painter.drawEllipse(QPointF(200, 200), 150, 26)

        painter.setBrush(_ISLAND_BACK)
        painter.drawPath(self._island_back)
        painter.setBrush(_ISLAND_FRONT)
        painter.drawPath(self._island_front)

        painter.setBrush(_PALM)
        painter.drawEllipse(QPointF(150, 70), 7, 7)
        painter.drawEllipse(QPointF(240, 86), 6, 6)
        painter.setPen(QPen(_PALM, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(150, 70), QPointF(150, 96))
        painter.drawLine(QPointF(240, 86), QPointF(240, 108))

        painter.restore()

    def _paint_ocean_and_waves(self, painter: QPainter, px: float, py: float) -> None:
        w, h = self.width(), self.height()
        band_top = h * (1.0 - _OCEAN_BAND_FRAC)
        band_height = h * _OCEAN_BAND_FRAC

        painter.save()
        painter.translate(px * 20, py * 6)

        gradient = QLinearGradient(0, band_top, 0, h)
        gradient.setColorAt(0.0, QColor(10, 126, 168, 0))
        gradient.setColorAt(0.55, QColor("#0a7ea8"))
        gradient.setColorAt(1.0, QColor("#063f56"))
        painter.fillRect(QRectF(0, band_top, w, band_height), gradient)

        period_px = max(200.0, w * _WAVE_PERIOD_FRAC)
        for index, layer in enumerate(_WAVE_LAYERS):
            baseline_y = band_top + band_height * layer.baseline_frac
            amplitude_px = band_height * layer.amplitude_frac
            offset = (self._elapsed_seconds / layer.period_seconds) * period_px
            offset %= period_px
            path = self._wave_path_cached(index, w, period_px, baseline_y, amplitude_px, h)
            color = QColor(layer.color)
            color.setAlphaF(layer.opacity)
            painter.save()
            # The cached path is built once at x_offset=0, with a full
            # extra period of margin baked in on each side (see
            # _wave_path) -- translating it by the per-tick drift instead
            # of rebuilding it from scratch is exactly equivalent, since
            # offset never exceeds one period.
            painter.translate(-offset, 0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPath(path)
            painter.restore()

        painter.restore()

    def _wave_path_cached(
        self,
        index: int,
        widget_width: float,
        period_px: float,
        baseline_y: float,
        amplitude_px: float,
        bottom_y: float,
    ) -> QPainterPath:
        key = (widget_width, period_px, baseline_y, amplitude_px, bottom_y)
        cached = self._wave_path_cache.get(index)
        if cached is not None and cached[0] == key:
            return cached[1]
        path = _wave_path(widget_width, period_px, baseline_y, amplitude_px, bottom_y, x_offset=0.0)
        self._wave_path_cache[index] = (key, path)
        return path

    def _paint_orbs(self, painter: QPainter, px: float, py: float) -> None:
        painter.save()
        painter.translate(px * 26, py * 10)
        for orb in _ORBS:
            t = self._elapsed_seconds - orb.delay_seconds
            # orb-float keyframes: 0% and 100% at rest, 50% at peak(dx,dy),
            # eased continuously between -- a raised cosine reaches 0 at
            # t=0, 1 at t=T/2, and back to 0 at t=T without ever pausing or
            # going negative, matching that shape without a full keyframe
            # evaluator.
            swing = 0.0 if t < 0 else (1 - math.cos(2 * math.pi * t / orb.duration_seconds)) / 2
            cx = self.width() * orb.left_frac + orb.dx * swing
            cy = self.height() * orb.top_frac + orb.dy * swing

            gradient = QRadialGradient(cx, cy, orb.size / 2)
            gradient.setColorAt(0.0, QColor(255, 255, 255, 217))
            gradient.setColorAt(0.45, QColor(127, 231, 255, 115))
            gradient.setColorAt(1.0, QColor(10, 126, 168, 20))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(cx, cy), orb.size / 2, orb.size / 2)
        painter.restore()

    def _paint_wind_streaks(self, painter: QPainter) -> None:
        w = self.width()
        for streak in _WIND_STREAKS:
            t = self._elapsed_seconds - streak.delay_seconds
            if t < 0:
                continue
            progress = (t % streak.duration_seconds) / streak.duration_seconds
            # wind-streak keyframes: fade in by 15%, hold, fade out over the
            # last 15%, sweeping from -20% to 120% of its own width across
            # the widget's full width.
            if progress < 0.15:
                opacity = 0.55 * (progress / 0.15)
            elif progress > 0.85:
                opacity = 0.4 * (1 - (progress - 0.85) / 0.15)
            else:
                opacity = 0.5
            x = -0.2 * w + progress * 1.4 * w
            y = self.height() * streak.top_frac

            gradient = QLinearGradient(x, y, x + _WIND_STREAK_WIDTH, y)
            gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
            gradient.setColorAt(0.5, QColor(255, 255, 255, int(255 * opacity)))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(QPen(QBrush(gradient), 2))
            painter.drawLine(QPointF(x, y), QPointF(x + _WIND_STREAK_WIDTH, y))

    def _paint_stars(self, painter: QPainter) -> None:
        for star in _STARS:
            t = self._elapsed_seconds - star.delay_seconds
            # Same raised-cosine shape as the orbs: 0 at t=0/T, 1 at t=T/2 --
            # matches the twinkle keyframes' 0%/50%/100% timing exactly.
            phase = 0.0 if t < 0 else (1 - math.cos(2 * math.pi * t / star.period_seconds)) / 2
            opacity = 0.25 + 0.65 * phase  # twinkle keyframes: 0.25 .. 0.9
            color = QColor(255, 255, 255)
            color.setAlphaF(opacity)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            cx, cy = self.width() * star.left_frac, self.height() * star.top_frac
            painter.drawEllipse(QPointF(cx, cy), star.radius, star.radius)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _build_island_paths() -> tuple[QPainterPath, QPainterPath]:
    """Back/front island silhouettes, ported directly from Dashboard.dc.html's
    two <path> elements (in that SVG's own 400x220 local coordinate space --
    scaled/positioned onto the widget in _paint_island)."""
    back = QPainterPath()
    back.moveTo(60, 190)
    back.quadTo(90, 90, 170, 80)
    back.quadTo(210, 74, 235, 100)
    back.quadTo(280, 90, 310, 130)
    back.quadTo(330, 150, 300, 190)
    back.closeSubpath()

    front = QPainterPath()
    front.moveTo(60, 190)
    front.quadTo(90, 100, 165, 90)
    front.quadTo(200, 86, 225, 108)
    front.quadTo(222, 150, 210, 190)
    front.closeSubpath()

    return back, front


def _wave_path(
    widget_width: float,
    period_px: float,
    baseline_y: float,
    amplitude_px: float,
    bottom_y: float,
    *,
    x_offset: float,
) -> QPainterPath:
    """One periodic hump-and-trough wave band, wide enough (with a period
    of margin on each side) that ``x_offset`` can drift it seamlessly
    without ever exposing an edge -- matches the prototype's alternating
    quadratic "T" (reflected-control-point) wave path, generated
    programmatically here rather than hand-transcribed per layer."""
    half = period_px / 2
    path = QPainterPath()
    start_x = x_offset - period_px
    path.moveTo(start_x, baseline_y)
    x = start_x
    up = True
    end_x = widget_width + period_px
    while x < end_x:
        control_y = baseline_y - amplitude_px if up else baseline_y + amplitude_px
        next_x = x + half
        path.quadTo(x + half / 2, control_y, next_x, baseline_y)
        x = next_x
        up = not up
    path.lineTo(x, bottom_y)
    path.lineTo(start_x, bottom_y)
    path.closeSubpath()
    return path
