"""A tab-bar-style widget built from ``PillButton``s instead of ``QTabBar``.

``pill_button.PillButton`` (see its module docstring) paints its own
antialiased rounded background directly instead of relying on QSS
``border-radius``, which this app's Qt/PySide6 build does not reliably
honor on stock widgets. Rather than reimplement that same direct-paint
fix on ``QTabBar`` (a more complex widget to override correctly -- it
owns multi-tab layout, overlap, and scroll-button behavior that
``PillButton`` doesn't have to deal with), this widget sidesteps
``QTabBar`` entirely: a plain horizontal row of checkable ``PillButton``s
(styled as segmented pills via the existing ``#PlatformPill`` QSS rule --
the same idle/active language Testing's own Unity platform selector
already uses) driving a ``QStackedWidget``, exposing just enough of
``QTabWidget``'s API (``addTab``, ``setCurrentIndex``) for it to be a
drop-in replacement at every call site in ``ui.screens.testing``.
"""

from __future__ import annotations

from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from spiced.ui.widgets.pill_button import PillButton


class PillTabWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self._tab_row = QHBoxLayout()
        self._tab_row.setSpacing(6)
        outer.addLayout(self._tab_row)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

    def addTab(self, widget: QWidget, label: str) -> int:  # noqa: N802 (QTabWidget-compatible API)
        index = self._stack.count()
        btn = PillButton(label)
        btn.setObjectName("PlatformPill")
        btn.setCheckable(True)
        btn.clicked.connect(lambda _checked, i=index: self.setCurrentIndex(i))
        self._group.addButton(btn, index)
        self._tab_row.addWidget(btn)
        self._stack.addWidget(widget)
        if index == 0:
            btn.setChecked(True)
        return index

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 (QTabWidget-compatible API)
        self._stack.setCurrentIndex(index)
        button = self._group.button(index)
        if button is not None:
            button.setChecked(True)

    def count(self) -> int:
        return self._stack.count()
