"""Water-drop splash: a transient click-feedback ripple.

Attached to a button via ``attach_splash`` at construction time rather than
folded into the button's own ``paintEvent`` -- ``PillButton`` already
self-paints for its own reasons (QSS ``border-radius`` isn't trustworthy on
this Qt build, see its module docstring); stacking a second, unrelated
paint concern into that same override would tangle them together. A splash
is a sibling overlay widget instead: ``WA_TransparentForMouseEvents`` so it
never intercepts the real click, and it deletes itself once its animation
finishes -- callers never manage its lifetime.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from spiced.ui.effects.motion import current_reduced_motion, reduced_motion

# ui.theme's aqua accent ramp bright highlight -- the default splash color
# for any button that doesn't pass its own.
SPLASH_COLOR = QColor("#7FE7FF")

_DURATION_MS = 420


class WaterSplashOverlay(QWidget):
    """A short-lived ripple ring plus a settling drop dot, centered on
    ``origin`` (in ``parent``'s own coordinates) and sized to cover
    ``parent``'s full rect. Deletes itself once its animation finishes."""

    def __init__(
        self, parent: QWidget, origin: QPoint, color: QColor = SPLASH_COLOR
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(parent.rect())
        self._origin = origin
        self._color = color
        self._progress = 0.0  # 0..1, driven by the animation below

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(_DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_value_changed)
        self._anim.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        self._anim.start()

    def _on_value_changed(self, value: float) -> None:
        self._progress = value
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: ARG002 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        max_radius = max(self.width(), self.height()) * 0.9
        radius = max_radius * self._progress
        ring_color = QColor(self._color)
        ring_color.setAlphaF(0.65 * (1 - self._progress))
        painter.setPen(QPen(ring_color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(self._origin, radius, radius)

        # A small settling "drop" dot for the bounce feel: grows fast, then
        # eases back slightly while the ring keeps expanding past it.
        drop_radius = 7 * min(1.0, self._progress * 3) * (1.15 - 0.15 * self._progress)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(self._origin, drop_radius, drop_radius)


def attach_splash(
    button: QWidget, services: object | None = None, *, color: QColor = SPLASH_COLOR
) -> None:
    """Make ``button`` show a water-drop splash on every real click.

    Call once per button at construction time. ``services`` is optional --
    pass it when the widget already has one on hand (e.g.
    ``NotificationBell``); omit it for widgets built at many call sites with
    no ``Services`` threaded through (e.g. ``PillButton``), which falls back
    to whatever was last registered via ``motion.set_active_services``.
    """
    original_release = button.mouseReleaseEvent

    def _handler(event: QMouseEvent) -> None:
        skip = reduced_motion(services) if services is not None else current_reduced_motion()
        if not skip:
            WaterSplashOverlay(button, event.position().toPoint(), color)
        original_release(event)  # never blocks the real click

    button.mouseReleaseEvent = _handler
