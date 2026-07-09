"""The main application window: sidebar · workspace · context panel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.ui.context_panel import ContextPanel
from spiced.ui.screens.base import PlaceholderScreen
from spiced.ui.screens.debugging import DebuggingScreen
from spiced.ui.screens.projects import ProjectsScreen
from spiced.ui.screens.settings import SettingsScreen
from spiced.ui.screens.testing import TestingScreen

NAV_ITEMS = [
    "Projects",
    "Debugging Buddy",
    "Automated Testing",
    "Feedback Review",
    "Settings",
]


class MainWindow(QWidget):
    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self.setObjectName("Root")
        self.setWindowTitle("Spiced")
        self.resize(1180, 760)
        self.setMinimumSize(920, 600)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        self._context = ContextPanel(services)
        self._context.setFixedWidth(280)

        root.addWidget(self._build_sidebar(), 0)
        root.addWidget(self._build_workspace(), 1)
        root.addWidget(self._context, 0)

        self._nav_buttons[0].setChecked(True)
        self._stack.setCurrentIndex(0)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(4)

        brand = QLabel("Spiced")
        brand.setObjectName("Brand")
        layout.addWidget(brand)
        tagline = QLabel("Your calm dev companion")
        tagline.setObjectName("Tagline")
        tagline.setWordWrap(True)
        layout.addWidget(tagline)
        layout.addSpacing(10)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        for index, name in enumerate(NAV_ITEMS):
            btn = QPushButton(name)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, i=index: self._stack.setCurrentIndex(i))
            self._nav_group.addButton(btn, index)
            self._nav_buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch(1)
        version = QLabel("MVP preview · Phase 2")
        version.setObjectName("Muted")
        layout.addWidget(version)
        return sidebar

    def _build_workspace(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(6, 6, 6, 6)

        self._stack = QStackedWidget()

        self._projects_screen = ProjectsScreen(self._services)
        self._debugging_screen = DebuggingScreen(self._services)
        self._testing_screen = TestingScreen(self._services)
        self._projects_screen.projects_changed.connect(self._context.refresh)
        self._projects_screen.projects_changed.connect(self._debugging_screen.refresh)
        self._projects_screen.projects_changed.connect(self._testing_screen.refresh)

        self._debugging_screen.usage_changed.connect(self._context.refresh)
        self._testing_screen.usage_changed.connect(self._context.refresh)

        self._settings_screen = SettingsScreen(self._services)
        self._settings_screen.settings_changed.connect(self._context.refresh)

        self._stack.addWidget(self._projects_screen)
        self._stack.addWidget(self._debugging_screen)
        self._stack.addWidget(self._testing_screen)
        self._stack.addWidget(
            PlaceholderScreen(
                "Feedback Review",
                "Bring in player feedback and playtest notes, and Spiced will help you "
                "find themes and turn them into clear, actionable tasks.",
                [
                    "Group similar feedback into themes",
                    "Draft respectful reply summaries",
                    "Highlight recurring pain points",
                ],
            )
        )
        self._stack.addWidget(self._settings_screen)

        outer.addWidget(self._stack)
        return panel
