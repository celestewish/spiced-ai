"""Help & About: what Spiced is, what it will and won't do, and where data lives.

A calm reference screen. It repeats the onboarding promises so they are always
one click away, offers a safe way to load (or reset) the bundled demo, and can
replay the welcome dialog. Nothing here contacts an AI provider or the network.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services


class HelpScreen(QWidget):
    """Mission, capabilities, safety boundaries, provider setup, and data location."""

    # The main window performs the work; the screen only asks.
    demo_requested = Signal(bool)  # fresh?
    replay_welcome_requested = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title = QLabel("Help & About")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        lead = QLabel(
            "Spiced helps indie developers review bugs, tests, and player feedback "
            "without taking creative control away from them."
        )
        lead.setObjectName("WelcomeLead")
        lead.setWordWrap(True)
        layout.addWidget(lead)

        layout.addWidget(
            self._card(
                "What Spiced helps with",
                [
                    "Make sense of Unity error logs in the Debugging Buddy.",
                    "Organize manual test cases and review imported test results.",
                    "Turn messy player feedback into clear themes and action items.",
                    "See a calm project dashboard with a cautious readiness read.",
                ],
            )
        )

        layout.addWidget(
            self._card(
                "What Spiced will not do",
                [
                    "It never runs Unity or any engine command.",
                    "It never edits or deletes your project files.",
                    "It never sends anything to an AI provider unless you ask.",
                    "It never claims your game is ready to ship — you decide.",
                ],
            )
        )

        layout.addWidget(
            self._card(
                "Setting up an AI provider",
                [
                    "The mock provider works offline with no key — great for a first look.",
                    "For OpenAI, set OPENAI_API_KEY in your environment or a local .env "
                    "(see .env.example), then pick OpenAI in Settings.",
                    "Use Settings → Send test prompt to confirm the connection. Only a "
                    "short fixed message is sent — never your files.",
                ],
            )
        )

        layout.addWidget(
            self._card(
                "Where your data lives",
                [
                    "Everything is stored locally in a SQLite database on this machine:",
                    self._services.db.path,
                    "Projects, settings, usage, and saved analyses stay on your computer.",
                ],
            )
        )

        demo_card = self._demo_card()
        layout.addWidget(demo_card)

        layout.addStretch(1)

    # --- Cards -------------------------------------------------------------

    def _card(self, heading: str, lines: list[str]) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(18, 16, 18, 16)
        inner.setSpacing(6)
        title = QLabel(heading)
        title.setObjectName("CardTitle")
        inner.addWidget(title)
        for line in lines:
            label = QLabel(f"•  {line}")
            label.setWordWrap(True)
            inner.addWidget(label)
        return card

    def _demo_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(18, 16, 18, 16)
        inner.setSpacing(6)

        title = QLabel("Try the demo project")
        title.setObjectName("CardTitle")
        inner.addWidget(title)

        desc = QLabel(
            "Load a small, self-contained sample project so you can explore every "
            "screen right away. It adds a debug session, test cases, a test run, and "
            "a feedback batch — all bundled sample data. No Unity is run, no real "
            "files are touched, and nothing is sent anywhere. Your own projects are "
            "never changed."
        )
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        inner.addWidget(desc)

        row = QHBoxLayout()
        load_btn = QPushButton("Load demo project")
        load_btn.clicked.connect(lambda: self.demo_requested.emit(False))
        row.addWidget(load_btn)
        reset_btn = QPushButton("Reset demo data")
        reset_btn.setObjectName("Ghost")
        reset_btn.clicked.connect(lambda: self.demo_requested.emit(True))
        row.addWidget(reset_btn)
        welcome_btn = QPushButton("Show welcome again")
        welcome_btn.setObjectName("Ghost")
        welcome_btn.clicked.connect(self.replay_welcome_requested.emit)
        row.addWidget(welcome_btn)
        row.addStretch(1)
        inner.addLayout(row)

        reset_note = QLabel(
            "“Reset demo data” only refreshes the bundled demo project. It never "
            "deletes projects you created yourself."
        )
        reset_note.setObjectName("Muted")
        reset_note.setWordWrap(True)
        inner.addWidget(reset_note)
        return card
