"""ui.effects.transitions: FadeStackedWidget's crossfade-on-switch behavior.

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching the pattern used by the other widget tests.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel  # noqa: E402

from spiced.ui.effects.transitions import FadeStackedWidget  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakeServices:
    def __init__(self, *, reduce_motion: bool) -> None:
        self._reduce_motion = reduce_motion

    def accessibility_reduce_motion_enabled(self) -> bool:
        return self._reduce_motion


def _stack(*, reduce_motion: bool) -> FadeStackedWidget:
    stack = FadeStackedWidget(services=_FakeServices(reduce_motion=reduce_motion))
    stack.addWidget(QLabel("Page 0"))
    stack.addWidget(QLabel("Page 1"))
    return stack


def test_switching_to_the_same_index_is_a_no_op():
    stack = _stack(reduce_motion=False)
    stack.setCurrentIndex(0)
    stack.setCurrentIndex(0)
    assert stack.currentIndex() == 0
    assert stack._anim is None


def test_reduced_motion_switches_instantly_with_no_animation():
    stack = _stack(reduce_motion=True)
    stack.setCurrentIndex(1)
    assert stack.currentIndex() == 1
    assert stack._anim is None
    assert stack.currentWidget().graphicsEffect() is None


def test_no_services_defaults_to_reduced_motion():
    stack = FadeStackedWidget()  # services=None
    stack.addWidget(QLabel("Page 0"))
    stack.addWidget(QLabel("Page 1"))
    stack.setCurrentIndex(1)
    assert stack.currentIndex() == 1
    assert stack._anim is None


def test_normal_switch_starts_a_fade_and_updates_the_index_immediately():
    stack = _stack(reduce_motion=False)
    stack.setCurrentIndex(1)

    # The underlying index changes synchronously -- currentChanged-driven
    # data refresh (e.g. MainWindow._on_stack_changed) isn't gated on the
    # fade animation's own timing.
    assert stack.currentIndex() == 1
    assert stack._anim is not None
    assert isinstance(stack.currentWidget().graphicsEffect(), QGraphicsOpacityEffect)


def test_fade_removes_the_opacity_effect_once_finished():
    stack = _stack(reduce_motion=False)
    stack.setCurrentIndex(1)
    incoming = stack.currentWidget()

    stack._anim.finished.emit()

    assert incoming.graphicsEffect() is None


def test_current_changed_still_fires_with_the_new_index():
    stack = _stack(reduce_motion=False)
    seen = []
    stack.currentChanged.connect(seen.append)

    stack.setCurrentIndex(1)

    assert seen == [1]
