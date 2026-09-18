"""The tutorial's closing hand-off dialog.

A centered ``QDialog``, not an overlay callout -- there's no widget left to
point at once the walkthrough's done. Same ``objectName("Panel")`` as
``TutorialOverlay``'s callout and ``ShortcutsCheatSheet``, so it reads as
the same dialog family rather than a one-off that only shows up once.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from spiced.ui.widgets.pill_button import PillButton


class TutorialFinishDialog(QDialog):
    connect_project_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setWindowTitle("Nice work")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        title = QLabel("That's a real crash analysis")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        body = QLabel(
            "Start to finish, using the sample project -- no setup required. Ready to "
            "connect your own Unity project?"
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        buttons = QHBoxLayout()
        maybe_later_btn = PillButton("Maybe later", ghost=True)
        maybe_later_btn.clicked.connect(self.accept)
        buttons.addWidget(maybe_later_btn)
        buttons.addStretch(1)
        connect_btn = PillButton("Connect a project")
        connect_btn.clicked.connect(self._on_connect_clicked)
        buttons.addWidget(connect_btn)
        layout.addLayout(buttons)

    def _on_connect_clicked(self) -> None:
        self.connect_project_requested.emit()
        self.accept()
