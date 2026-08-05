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
from spiced.ui.build_scheduler import BuildScheduler
from spiced.ui.context_panel import ContextPanel
from spiced.ui.screens.animation import AnimationScreen
from spiced.ui.screens.art import ArtScreen
from spiced.ui.screens.audio import AudioScreen
from spiced.ui.screens.business import BusinessScreen
from spiced.ui.screens.dashboard import DashboardScreen
from spiced.ui.screens.debugging import DebuggingScreen
from spiced.ui.screens.feedback import FeedbackScreen
from spiced.ui.screens.marketing import MarketingScreen
from spiced.ui.screens.projects import ProjectsScreen
from spiced.ui.screens.roadmap import RoadmapScreen
from spiced.ui.screens.settings import SettingsScreen
from spiced.ui.screens.shaders_vfx import ShadersVfxScreen
from spiced.ui.screens.team import TeamScreen
from spiced.ui.screens.testing import TestingScreen

NAV_ITEMS = [
    "Dashboard",
    "Projects",
    "Debugging Buddy",
    "Automated Testing",
    "Feedback Review",
    # Marketing (Phase G, section 7): a new sidebar page per spec, sitting
    # alongside the other tool pages rather than folded into an existing one
    # — Store Page Advisor / Wishlist Analytics / Screenshot Checklist don't
    # naturally belong to Debugging, Testing, or Feedback.
    "Marketing",
    # Business (Phase H, section 7 part 2): a new sidebar page per spec, for
    # Contract/License Checklist, Budget/Runway Tracker, Grant/Funding
    # Finder, and Competitive Landscape Scan — none of these naturally
    # belong on an existing tool page either.
    "Business",
    # Team Collaboration by Role: Art + Audio + Animation (Phase I, section
    # 8 part 1) — three new sidebar pages per spec, one per role.
    "Art",
    "Audio",
    "Animation",
    # Shaders & VFX + Cross-Role & Team Glue (Phase J, section 8 part 2) —
    # two more new sidebar pages per spec: Shaders/VFX (Shader Performance
    # Profiling, Visual Regression Testing) and Team (Unified Task Board,
    # discipline self-service, comment threads). Role-Based Dashboards (#4)
    # lives on the Context Panel instead (it's a summary, not its own
    # screen); Relevance-Based Notifications' routing config lives on the
    # Settings screen (see SettingsScreen) rather than getting its own page,
    # since Section 9's Notification Center (the actual inbox UI) is a
    # later phase (Phase K) this one deliberately doesn't build.
    "Shaders/VFX",
    "Team",
    # Roadmap sits outside the tool pages above, next to Settings — per the
    # Section 5 spec's placement call.
    "Roadmap",
    "Settings",
]

_DASHBOARD_INDEX = 0


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

        # Automated Build Pipeline (Phase D): in-app-only nightly scheduler.
        # Lives for as long as this window does; a failure is a quiet Context
        # Panel note, a success (or failure) also refreshes Testing's history.
        self._build_scheduler = BuildScheduler(self._services, self)
        self._build_scheduler.build_failed.connect(self._context.show_build_failure)
        self._build_scheduler.build_report_saved.connect(self._testing_screen.refresh)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._build_scheduler.stop()
        super().closeEvent(event)

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
        self._marketing_screen = MarketingScreen(self._services)
        self._business_screen = BusinessScreen(self._services)
        self._art_screen = ArtScreen(self._services)
        self._audio_screen = AudioScreen(self._services)
        self._animation_screen = AnimationScreen(self._services)
        self._shaders_vfx_screen = ShadersVfxScreen(self._services)
        self._team_screen = TeamScreen(self._services)
        self._projects_screen.projects_changed.connect(self._context.refresh)
        self._projects_screen.projects_changed.connect(self._debugging_screen.refresh)
        self._projects_screen.projects_changed.connect(self._testing_screen.refresh)
        self._projects_screen.projects_changed.connect(self._feedback_screen.refresh)
        self._projects_screen.projects_changed.connect(self._marketing_screen.refresh)
        self._projects_screen.projects_changed.connect(self._business_screen.refresh)
        self._projects_screen.projects_changed.connect(self._art_screen.refresh)
        self._projects_screen.projects_changed.connect(self._audio_screen.refresh)
        self._projects_screen.projects_changed.connect(self._animation_screen.refresh)
        self._projects_screen.projects_changed.connect(self._shaders_vfx_screen.refresh)
        self._projects_screen.projects_changed.connect(self._team_screen.refresh)
        self._projects_screen.projects_changed.connect(self._dashboard_screen.refresh)
        # SettingsScreen's notification routing panel (#6) is also
        # project-scoped (routing rules are per-team) -- connected below,
        # once self._settings_screen exists.

        # New AI analyses create debug/test/feedback/marketing/business
        # records, so refresh the dashboard (and usage pill) whenever one
        # completes. Art/Audio/Animation/Shaders-VFX involve no AI calls,
        # but they still emit usage_changed after a scan completes so their
        # own history panels + the dashboard stay in sync, same as the
        # local-only sections of Marketing/Business. Team involves no AI
        # call either, but emits usage_changed after a task/comment mutation
        # for the same reason.
        self._debugging_screen.usage_changed.connect(self._context.refresh)
        self._testing_screen.usage_changed.connect(self._context.refresh)
        self._feedback_screen.usage_changed.connect(self._context.refresh)
        self._marketing_screen.usage_changed.connect(self._context.refresh)
        self._business_screen.usage_changed.connect(self._context.refresh)
        self._art_screen.usage_changed.connect(self._context.refresh)
        self._audio_screen.usage_changed.connect(self._context.refresh)
        self._animation_screen.usage_changed.connect(self._context.refresh)
        self._shaders_vfx_screen.usage_changed.connect(self._context.refresh)
        self._team_screen.usage_changed.connect(self._context.refresh)
        self._debugging_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._testing_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._feedback_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._marketing_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._business_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._art_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._audio_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._animation_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._shaders_vfx_screen.usage_changed.connect(self._dashboard_screen.refresh)
        self._team_screen.usage_changed.connect(self._dashboard_screen.refresh)

        self._roadmap_screen = RoadmapScreen(self._services)

        self._settings_screen = SettingsScreen(self._services)
        self._settings_screen.settings_changed.connect(self._context.refresh)
        # Team Mode toggling changes whether the Testing screen's Build
        # Health badge shows its team-linked note. Rapid Prototyping Mode
        # toggling changes which panel the Testing screen foregrounds.
        self._settings_screen.settings_changed.connect(self._testing_screen.refresh)
        # The notification routing panel (#6) needs to reload whenever the
        # active project (and therefore its team) changes.
        self._projects_screen.projects_changed.connect(self._settings_screen.refresh)

        self._stack.addWidget(self._dashboard_screen)
        self._stack.addWidget(self._projects_screen)
        self._stack.addWidget(self._debugging_screen)
        self._stack.addWidget(self._testing_screen)
        self._stack.addWidget(self._feedback_screen)
        self._stack.addWidget(self._marketing_screen)
        self._stack.addWidget(self._business_screen)
        self._stack.addWidget(self._art_screen)
        self._stack.addWidget(self._audio_screen)
        self._stack.addWidget(self._animation_screen)
        self._stack.addWidget(self._shaders_vfx_screen)
        self._stack.addWidget(self._team_screen)
        self._stack.addWidget(self._roadmap_screen)
        self._stack.addWidget(self._settings_screen)
        # Recompute the dashboard whenever the user navigates to it.
        self._stack.currentChanged.connect(self._on_stack_changed)

        outer.addWidget(self._stack)
        return panel

    def _on_stack_changed(self, index: int) -> None:
        if index == _DASHBOARD_INDEX:
            self._dashboard_screen.refresh()
