"""A QComboBox that doesn't hijack mouse-wheel scrolling.

By default, Qt gives every QComboBox first claim on wheel events under the
cursor -- scrolling the mouse wheel while hovering over one changes its
selected value instead of scrolling whatever it's sitting inside. Every
screen with more than a couple of sections lives inside a QScrollArea (see
the pattern in e.g. ``ui.screens.settings``), and several of those screens
have many QComboBoxes stacked down the page -- so scrolling through the page
routinely drags the cursor over one, silently changing its value. The
"Text size" combo box on Settings makes this especially visible: scrolling
past it flips the whole app's font size, live, as a side effect of trying to
scroll the page.

``ScrollSafeComboBox`` fixes this the standard Qt way: a wheel event over an
unfocused combo box is ignored (not consumed), which Qt then propagates up
to the nearest ancestor that wants it -- the enclosing QScrollArea. Once the
combo box actually has focus (the user clicked into it, or tabbed to it),
wheel events behave normally, so scrolling to pick a value still works for
someone deliberately interacting with it.

Use this in place of ``QComboBox`` for every new/existing combo box in the
UI -- there's no reason to ever want the hijack-on-hover behavior here.
"""

from __future__ import annotations

from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QComboBox


class ScrollSafeComboBox(QComboBox):
    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)
