"""ScrollSafeComboBox ignores wheel events unless focused, so scrolling a
page full of combo boxes never silently changes one's value (see the
module's own docstring for the bug this fixes -- the "Text size" combo box
on Settings flipping the whole app's font live as a side effect of
scrolling past it).

No display is available in this environment, so this uses Qt's offscreen
platform plugin (set before the first PySide6 import) to instantiate real
widgets headlessly rather than skipping widget-level testing entirely.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF  # noqa: E402
from PySide6.QtGui import Qt, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.ui.widgets.scroll_safe_combo_box import ScrollSafeComboBox  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _wheel_event() -> QWheelEvent:
    return QWheelEvent(
        QPointF(0, 0),
        QPointF(0, 0),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_wheel_event_is_ignored_when_unfocused():
    box = ScrollSafeComboBox()
    box.addItems(["small", "normal", "large"])
    box.setCurrentIndex(1)
    assert box.hasFocus() is False

    event = _wheel_event()
    box.wheelEvent(event)

    assert event.isAccepted() is False
    assert box.currentIndex() == 1  # unchanged


def test_wheel_event_is_handled_normally_when_focused(monkeypatch):
    # Real OS-level focus is unreliable under the offscreen platform plugin
    # in a headless test run, so this exercises wheelEvent's actual branch
    # logic directly rather than depending on a real focus grab succeeding.
    box = ScrollSafeComboBox()
    box.addItems(["small", "normal", "large"])
    box.setCurrentIndex(1)
    monkeypatch.setattr(box, "hasFocus", lambda: True)

    event = _wheel_event()
    box.wheelEvent(event)

    assert event.isAccepted() is True
