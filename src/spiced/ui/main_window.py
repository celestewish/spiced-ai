"""The main application window: sidebar · workspace · context panel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.ui.context_panel import ContextPanel
from spiced.ui.screens.dashboard import DashboardScreen
from spiced.ui.screens.debugging import DebuggingScreen
from spiced.ui.screens.feedback import FeedbackScreen
from spiced.ui.screens.onboarding import (
    ACTION_CONFIGURE_AI,
    ACTION_CREATE_PROJECT,
    ACTION_LOAD_DEMO,
    OnboardingScreen,
)
from spiced.ui.screens.projects import ProjectsScreen
from spiced.ui.screens.settings import SettingsScreen
from spiced.ui.screens.testing import TestingScreen

NAV_ITEMS = [
    "Dashboard",
    "Projects",
    "Debugging Buddy",
    "Automated Testing",
    "Feedback Review",
    "Settings",
]

_DASHBOARD_INDEX = 0
_PROJECTS_INDEX = 1
_SETTINGS_INDEX = 5
# Onboarding lives past the nav-mapped screens so it has no sidebar button.
_ONBOARDING_INDEX = len(NAV_ITEMS)


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

        if self._services.onboarding_completed():
            self._navigate(_DASHBOARD_INDEX)
        else:
            self._stack.setCurrentIndex(_ONBOARDING_INDEX)

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
        version = QLabel("MVP preview · Phase 4")
        version.setObjectName("Muted")
        layout.addWidget(version)
        return sidebar

    def _build_workspace(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(6, 6, 6, 6)

        self._stack = QStackedWidget()

        self._dashboard_screen = DashboardScreen(self._services)
        self._projects_screen = ProjectsScreen(self._services)
        self._debugging_screen = DebuggingScreen(self._services)
        self._testing_screen = TestingScreen(self._services)
        self._feedback_screen = FeedbackScreen(self._services)
        self._projects_screen.projects_changed.connect(self._context.refresh)
        self._projects_screen.projects_changed.connect(self._debugging_screen.refresh)
        self._projects_screen.projects_changed.connect(self._testing_screen.refresh)
        self._projects_screen.projects_changed.connect(self._feedback_screen.refresh)
        self._projects_screen.projects_changed.connect(self._dashboard_screen.refresh)

        # New AI analyses create debug/test/feedback records, so refresh the
        # dashboard (and usage pill) whenever one completes.
        self._debugging_screen.usage_changed.connect(self._context.refresh)
        self._testing_screen.usage_changed.connect(self._context.refresh)
        self._feedback_screen.usage_changed.connect(self._context.refresh)
        self._debugging_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._testing_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._feedback_screen.usage_changed.connect(self._dashboard_screen.refresh)

        self._settings_screen = SettingsScreen(self._services)
        self._settings_screen.settings_changed.connect(self._context.refresh)
        self._settings_screen.reopen_onboarding.connect(self._show_onboarding)

        self._onboarding_screen = OnboardingScreen()
        self._onboarding_screen.action_selected.connect(self._on_onboarding_action)

        self._stack.addWidget(self._dashboard_screen)
        self._stack.addWidget(self._projects_screen)
        self._stack.addWidget(self._debugging_screen)
        self._stack.addWidget(self._testing_screen)
        self._stack.addWidget(self._feedback_screen)
        self._stack.addWidget(self._settings_screen)
        self._stack.addWidget(self._onboarding_screen)
        # Recompute the dashboard whenever the user navigates to it.
        self._stack.currentChanged.connect(self._on_stack_changed)

        outer.addWidget(self._stack)
        return panel

    def _on_stack_changed(self, index: int) -> None:
        if index == _DASHBOARD_INDEX:
            self._dashboard_screen.refresh()

    def _navigate(self, index: int) -> None:
        """Switch to a nav-mapped screen and keep the sidebar in sync."""
        if 0 <= index < len(self._nav_buttons):
            self._nav_buttons[index].setChecked(True)
        self._stack.setCurrentIndex(index)

    def _show_onboarding(self) -> None:
        """Reopen onboarding on demand. Never resets settings, projects, or data."""
        self._stack.setCurrentIndex(_ONBOARDING_INDEX)

    def _on_onboarding_action(self, action: str) -> None:
        # Completing, skipping, or picking a first step all finish onboarding so
        # it does not auto-show again. Reopening later is manual and non-resetting.
        self._services.set_onboarding_completed(True)
        if action == ACTION_CREATE_PROJECT:
            self._navigate(_PROJECTS_INDEX)
        elif action == ACTION_CONFIGURE_AI:
            self._navigate(_SETTINGS_INDEX)
        elif action == ACTION_LOAD_DEMO:
            self._load_demo_from_onboarding()
        else:  # ACTION_DASHBOARD or ACTION_SKIP
            self._navigate(_DASHBOARD_INDEX)

    def _load_demo_from_onboarding(self) -> None:
        # Reuses the existing Phase 5A demo service (repeat-safe, no Unity, no AI,
        # nothing sent anywhere, never touches the developer's own projects).
        project = self._services.load_demo_project()
        self._refresh_after_data_change()
        self._navigate(_DASHBOARD_INDEX)
        QMessageBox.information(
            self,
            project.name,
            "Demo project loaded. Open the Dashboard to see how Spiced summarizes "
            "debugging, testing, and feedback signals.",
        )

    def _refresh_after_data_change(self) -> None:
        self._context.refresh()
        self._projects_screen.refresh()
        self._debugging_screen.refresh()
        self._testing_screen.refresh()
        self._feedback_screen.refresh()
        self._dashboard_screen.refresh()
