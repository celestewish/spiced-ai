"""A collapsible section with a clickable header: title + optional extra
header widgets (a status pill, a toggle switch) + a chevron, and a body that
shows/hides. Used by the Projects and Feedback Review screen redesigns to
turn several always-expanded settings sections into "collapsed by default,
one click to see the rest" -- see ui.screens.projects and
ui.screens.feedback.

Deliberately generic about *how* it expands: a header click always toggles
it (``_on_header_clicked``), and callers that want a checkbox to also drive
expansion (e.g. Feedback Review's Community Pulse toggle) just connect that
checkbox's own ``toggled`` signal to ``set_expanded`` -- this widget doesn't
assume there is one.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class AccordionSection(QFrame):
    toggled = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        self._header = QWidget()
        self._header.setObjectName("AccordionHeader")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(4, 4, 4, 4)
        header_layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        header_layout.addWidget(title_label)

        # Callers add a status pill / toggle switch here, before the chevron
        # -- see ui.screens.projects's accordion wiring.
        self.header_extra = QHBoxLayout()
        self.header_extra.setSpacing(8)
        header_layout.addLayout(self.header_extra)

        header_layout.addStretch(1)

        self._chevron = QLabel("▸")
        header_layout.addWidget(self._chevron)
        outer.addWidget(self._header)

        self._body = QWidget()
        self.body_layout = QVBoxLayout(self._body)
        self.body_layout.setContentsMargins(4, 8, 4, 0)
        self.body_layout.setSpacing(6)
        outer.addWidget(self._body)
        self._expanded = False
        self._body.setVisible(False)

        self._header.mousePressEvent = self._on_header_clicked  # noqa: ARG005

    def is_expanded(self) -> bool:
        # Tracked explicitly rather than read back from QWidget.isVisible(),
        # which only reflects real on-screen visibility (requires every
        # ancestor, including the top-level window, to actually be shown) --
        # unreliable before the window is shown, e.g. in headless tests.
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._body.setVisible(expanded)
        self._chevron.setText("▾" if expanded else "▸")
        self.toggled.emit(expanded)

    def _on_header_clicked(self, _event) -> None:
        self.set_expanded(not self.is_expanded())
