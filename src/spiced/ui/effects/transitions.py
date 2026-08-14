"""Crossfade page transitions: a QStackedWidget that fades instead of cutting.

FadeStackedWidget is a drop-in QStackedWidget replacement -- every existing
addWidget/currentChanged/setCurrentIndex call site (see ui.main_window) keeps
working unchanged, since setCurrentIndex is the only method overridden here
and the underlying index still changes synchronously, before the fade
starts (so currentChanged-driven refresh logic, e.g.
MainWindow._on_stack_changed, isn't affected by the animation's timing).

Only a plain opacity crossfade, deliberately: the vertical-slide flourish
some page-transition designs use isn't worth it here. QGraphicsOpacityEffect
is already the expensive part of this (it forces offscreen compositing);
stacking a geometry animation on top, on screens as complex as
ui.screens.debugging or ui.screens.testing, wouldn't read as meaningfully
better than a clean fade -- "no hard cut" is the actual goal.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget

from spiced.ui.effects.motion import reduced_motion

_DURATION_MS = 220


class FadeStackedWidget(QStackedWidget):
    def __init__(self, parent: QWidget | None = None, services: object | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._anim: QPropertyAnimation | None = None

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 (Qt override)
        if index == self.currentIndex() or reduced_motion(self._services):
            super().setCurrentIndex(index)
            return

        super().setCurrentIndex(index)
        incoming = self.currentWidget()
        if incoming is None:
            return

        effect = QGraphicsOpacityEffect(incoming)
        incoming.setGraphicsEffect(effect)
        effect.setOpacity(0.0)

        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(_DURATION_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        anim.finished.connect(lambda: incoming.setGraphicsEffect(None))
        self._anim = anim  # Qt won't keep this alive on its own
        anim.start()
