"""The main application window: top bar · sidebar · workspace · context panel."""

from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
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
from spiced.ui.command_palette import CommandPalette, PaletteItem
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
from spiced.ui.top_bar import TopBar

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
    # Settings screen (see SettingsScreen) rather than getting its own page
    # -- the actual inbox UI (Phase K, section 9 part 1) is a bell icon in
    # the new top bar (see ui.top_bar.TopBar), not a sidebar page.
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

        # Top bar (Phase K, section 9 part 1, foundation): a thin strip
        # above the existing three-region layout, holding the Multi-Project
        # Switcher (next to the wordmark) and the Notification Center's
        # bell icon (right-aligned) -- see ui.top_bar.TopBar.
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self._top_bar = TopBar(self._services)
        root.addWidget(self._top_bar, 0)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        self._context = ContextPanel(services)
        self._context.setFixedWidth(280)

        body.addWidget(self._build_sidebar(), 0)
        body.addWidget(self._build_workspace(), 1)
        body.addWidget(self._context, 0)

        self._nav_buttons[0].setChecked(True)
        self._stack.setCurrentIndex(0)

        # The top bar's project switcher fires the same projects_changed
        # cascade the Projects screen's own selection already triggers, so
        # every other screen updates exactly as it does today -- see
        # ProjectsScreen.projects_changed's existing connections below.
        self._top_bar.project_switched.connect(self._on_top_bar_project_switched)
        self._projects_screen.projects_changed.connect(self._top_bar.refresh)
        self._settings_screen.settings_changed.connect(self._top_bar.refresh)

        # Command Palette / Quick Search (Ctrl+K on Windows/Linux, Cmd+K on
        # macOS -- QKeySequence("Ctrl+K") maps the portable "Ctrl" text to
        # each platform's own standard modifier).
        self._command_palette = CommandPalette(self._build_palette_items, self)
        self._palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._palette_shortcut.activated.connect(self._command_palette.open)

        # Automated Build Pipeline (Phase D): in-app-only nightly scheduler.
        # Lives for as long as this window does; a failure is a quiet Context
        # Panel note, a success (or failure) also refreshes Testing's history.
        # It's also one of the Notification Center's wired event sources
        # (Phase K, #a) -- see BuildScheduler._notify_build_failure, which
        # creates a real Notification for a team-linked project alongside
        # this quiet note (the note stays the only surfacing for a
        # solo/local-only build, since Notifications require a team).
        self._build_scheduler = BuildScheduler(self._services, self)
        self._build_scheduler.build_failed.connect(self._context.show_build_failure)
        self._build_scheduler.build_report_saved.connect(self._testing_screen.refresh)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._build_scheduler.stop()
        self._top_bar.stop()
        super().closeEvent(event)

    def _on_top_bar_project_switched(self) -> None:
        """Relay the top bar's switcher into the exact same cascade the
        Projects screen's own selection change already triggers -- keeps
        the Projects screen's list highlight in sync too, not just every
        other screen's data."""
        self._projects_screen.refresh()
        self._projects_screen.projects_changed.emit()

    def _build_palette_items(self) -> list[PaletteItem]:
        """Built fresh on every Ctrl+K press (see CommandPalette.open) since
        projects and recent items change over the app's lifetime.

        Covers three representative recent-item types per spec (a recent
        debug session, test run, and feedback batch for the active
        project) -- each jumps to the screen that kind of record lives on,
        since none of those screens has a "jump to this exact record" deep
        link yet.
        """
        items: list[PaletteItem] = []
        for index, name in enumerate(NAV_ITEMS):
            items.append(
                PaletteItem(
                    kind="page",
                    label=name,
                    subtitle="Page",
                    action=lambda i=index: self._stack.setCurrentIndex(i),
                )
            )
        for project in self._services.projects.list_projects():
            items.append(
                PaletteItem(
                    kind="project",
                    label=project.name,
                    subtitle="Switch to this project",
                    action=lambda pid=project.id: self._switch_active_project(pid),
                )
            )

        active = self._services.active_project()
        if active is not None:
            debugging_index = NAV_ITEMS.index("Debugging Buddy")
            testing_index = NAV_ITEMS.index("Automated Testing")
            feedback_index = NAV_ITEMS.index("Feedback Review")
            for session in self._services.debugging.history(active.id, limit=3):
                label = session.detected_error_type or session.summary or (
                    f"Debug session #{session.id}"
                )
                items.append(
                    PaletteItem(
                        kind="recent",
                        label=label,
                        subtitle=f"Recent debug session ({session.created_at}) — Debugging Buddy",
                        action=lambda i=debugging_index: self._stack.setCurrentIndex(i),
                    )
                )
            for run in self._services.testing.history(active.id, limit=3):
                label = run.source_filename or f"Test run #{run.id}"
                items.append(
                    PaletteItem(
                        kind="recent",
                        label=label,
                        subtitle=f"Recent test run ({run.created_at}) — Automated Testing",
                        action=lambda i=testing_index: self._stack.setCurrentIndex(i),
                    )
                )
            for batch in self._services.feedback.history(active.id, limit=3):
                label = batch.source_label or f"Feedback batch #{batch.id}"
                items.append(
                    PaletteItem(
                        kind="recent",
                        label=label,
                        subtitle=f"Recent feedback batch ({batch.created_at}) — Feedback Review",
                        action=lambda i=feedback_index: self._stack.setCurrentIndex(i),
                    )
                )
        return items

    def _switch_active_project(self, project_id: int) -> None:
        self._services.set_active_project(project_id)
        self._on_top_bar_project_switched()
        self._top_bar.refresh()

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
