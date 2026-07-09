"""First-run welcome dialog.

A short, warm introduction to Spiced with four clear next steps. It explains
what Spiced is, what it helps with, and — just as importantly — what it will
never do without permission. The dialog only chooses a destination; the main
window performs the action, so this stays easy to test and reuse.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Action results the dialog can return.
ACTION_CREATE_PROJECT = "create_project"
ACTION_LOAD_DEMO = "load_demo"
ACTION_CONFIGURE_PROVIDER = "configure_provider"
ACTION_CONTINUE = "continue"


class WelcomeDialog(QDialog):
    """A calm first-run introduction. Returns a chosen next action via ``action``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to Spiced")
        self.setObjectName("WelcomeDialog")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.action = ACTION_CONTINUE

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(12)

        brand = QLabel("Spiced")
        brand.setObjectName("Brand")
        layout.addWidget(brand)

        pitch = QLabel(
            "Spiced helps indie developers review bugs, tests, and player feedback — "
            "without taking creative control away from them."
        )
        pitch.setObjectName("WelcomeLead")
        pitch.setWordWrap(True)
        layout.addWidget(pitch)

        helps = QLabel(
            "It works alongside you to:\n"
            "•  make sense of Unity error logs\n"
            "•  organize manual test cases and results\n"
            "•  turn messy player feedback into clear themes\n"
            "•  show a calm project dashboard with a cautious readiness read"
        )
        helps.setObjectName("Muted")
        helps.setWordWrap(True)
        layout.addWidget(helps)

        boundaries = QLabel(
            "What Spiced will not do: it never runs Unity, never edits your project files, "
            "and never sends anything to an AI provider without you asking. It suggests and "
            "explains — you make every decision."
        )
        boundaries.setObjectName("Muted")
        boundaries.setWordWrap(True)
        layout.addWidget(boundaries)

        steps = QLabel("A good first step:")
        steps.setObjectName("SectionTitle")
        layout.addSpacing(4)
        layout.addWidget(steps)

        # Primary path: load the safe demo so a reviewer sees Spiced working instantly.
        demo_btn = QPushButton("Load demo project")
        demo_btn.clicked.connect(lambda: self._choose(ACTION_LOAD_DEMO))
        layout.addWidget(demo_btn)
        demo_hint = QLabel(
            "Adds a local sample project (no Unity files, nothing sent anywhere) so you can "
            "explore every screen right away."
        )
        demo_hint.setObjectName("Muted")
        demo_hint.setWordWrap(True)
        layout.addWidget(demo_hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        create_btn = QPushButton("Create a project")
        create_btn.setObjectName("Ghost")
        create_btn.clicked.connect(lambda: self._choose(ACTION_CREATE_PROJECT))
        row.addWidget(create_btn)
        provider_btn = QPushButton("Configure AI provider")
        provider_btn.setObjectName("Ghost")
        provider_btn.clicked.connect(lambda: self._choose(ACTION_CONFIGURE_PROVIDER))
        row.addWidget(provider_btn)
        continue_btn = QPushButton("Continue to dashboard")
        continue_btn.setObjectName("Ghost")
        continue_btn.clicked.connect(lambda: self._choose(ACTION_CONTINUE))
        row.addWidget(continue_btn)
        layout.addLayout(row)

        footer = QLabel("You can reopen this from the Help screen anytime.")
        footer.setObjectName("Muted")
        footer.setWordWrap(True)
        footer.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)
        layout.addWidget(footer)

    def _choose(self, action: str) -> None:
        self.action = action
        self.accept()
