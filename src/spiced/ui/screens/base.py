"""Shared helpers for placeholder screens."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderScreen(QWidget):
    """A calm, honest 'coming soon' screen for features not built yet.

    The copy is deliberately grounded: it describes what the feature will help
    with, without promising autonomous magic.
    """

    def __init__(self, title: str, description: str, coming: list[str] | None = None) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        heading = QLabel(title)
        heading.setObjectName("ScreenTitle")
        layout.addWidget(heading)

        body = QLabel(description)
        body.setObjectName("Muted")
        body.setWordWrap(True)
        layout.addWidget(body)

        if coming:
            label = QLabel("Planned for a later phase:")
            label.setObjectName("SectionTitle")
            layout.addSpacing(8)
            layout.addWidget(label)
            for item in coming:
                bullet = QLabel(f"•  {item}")
                bullet.setObjectName("Muted")
                bullet.setWordWrap(True)
                layout.addWidget(bullet)

        layout.addStretch(1)
        note = QLabel(
            "Spiced works alongside you. It suggests and explains; you stay in control "
            "of every change to your project."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(note)
