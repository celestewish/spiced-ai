"""First-run onboarding: a calm welcome that explains Spiced and offers first steps.

The screen is intentionally passive. It only describes what Spiced does (and,
just as importantly, what it will not do on its own) and emits an action key
when the user picks a first step. MainWindow decides what each action means, so
this screen never navigates, seeds data, or touches storage itself.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# Action keys emitted by ``action_selected``. MainWindow maps these to flows.
ACTION_CREATE_PROJECT = "create_project"
ACTION_LOAD_DEMO = "load_demo"
ACTION_CONFIGURE_AI = "configure_ai"
ACTION_DASHBOARD = "dashboard"
ACTION_SKIP = "skip"

_HELPS_WITH = [
    "Debug Unity issues",
    "Organize tests",
    "Review player feedback",
    "Understand build readiness",
]

_DOES_NOT_DO = [
    "It does not run Unity",
    "It does not edit your project files",
    "It does not make design decisions for you",
    "It does not send data unless you explicitly start a provider-backed analysis",
]

_FIRST_STEPS = [
    (ACTION_CREATE_PROJECT, "Create a project", "Add your own game to keep Spiced organized."),
    (ACTION_LOAD_DEMO, "Load demo project", "Explore Spiced with a safe bundled sample."),
    (ACTION_CONFIGURE_AI, "Configure AI provider", "Choose a provider or stay fully offline."),
    (ACTION_DASHBOARD, "Continue to Dashboard", "Jump straight in and look around."),
]


class OnboardingScreen(QWidget):
    """A brief, human-centered welcome. Emits an action key; never navigates."""

    action_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(14)

        title = QLabel("Welcome to Spiced")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        welcome = QLabel(
            "Spiced helps indie developers review bugs, tests, and player feedback "
            "without taking creative control away from them. It works alongside you — "
            "suggesting and explaining, while you stay in charge of every change."
        )
        welcome.setObjectName("Muted")
        welcome.setWordWrap(True)
        layout.addWidget(welcome)

        layout.addWidget(self._bullet_section("What Spiced helps with", _HELPS_WITH))
        layout.addWidget(
            self._bullet_section("What Spiced does not do automatically", _DOES_NOT_DO)
        )

        steps_title = QLabel("Choose your first step")
        steps_title.setObjectName("SectionTitle")
        layout.addSpacing(4)
        layout.addWidget(steps_title)

        for action, label, hint in _FIRST_STEPS:
            layout.addWidget(self._step_row(action, label, hint))

        layout.addStretch(1)

        skip_row = QHBoxLayout()
        skip_row.addStretch(1)
        skip_btn = QPushButton("Skip for now")
        skip_btn.setObjectName("Ghost")
        skip_btn.clicked.connect(lambda: self.action_selected.emit(ACTION_SKIP))
        skip_row.addWidget(skip_btn)
        layout.addLayout(skip_row)

    def _bullet_section(self, heading: str, items: list[str]) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(6)

        label = QLabel(heading)
        label.setObjectName("SectionTitle")
        inner.addWidget(label)
        for item in items:
            bullet = QLabel(f"•  {item}")
            bullet.setObjectName("Muted")
            bullet.setWordWrap(True)
            inner.addWidget(bullet)
        return card

    def _step_row(self, action: str, label: str, hint: str) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(12)

        btn = QPushButton(label)
        if action != ACTION_DASHBOARD:
            btn.setObjectName("Ghost")
        btn.setMinimumWidth(190)
        btn.clicked.connect(lambda _checked=False, a=action: self.action_selected.emit(a))
        line.addWidget(btn, 0)

        hint_label = QLabel(hint)
        hint_label.setObjectName("Muted")
        hint_label.setWordWrap(True)
        hint_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(hint_label, 1)
        return row
