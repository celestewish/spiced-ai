"""The main application window: top bar · sidebar · workspace · context panel."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.keyboard_shortcuts import ACTIONS, binding_for, load_bindings
from spiced.ui import theme
from spiced.ui.build_scheduler import BuildScheduler
from spiced.ui.command_palette import CommandPalette, PaletteItem
from spiced.ui.context_panel import ContextPanel
from spiced.ui.effects.background_scene import OceanBackgroundWidget
from spiced.ui.effects.motion import set_active_services
from spiced.ui.effects.transitions import FadeStackedWidget
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
from spiced.ui.shortcuts_cheatsheet import ShortcutsCheatSheet
from spiced.ui.top_bar import TopBar
from spiced.ui.widgets.mascot_logo import MascotLogo
from spiced.ui.widgets.nav_icons import NavOrbButton

# Card/ReadinessCard frames are dashboard.py's -- rebuilt fresh on every
# refresh(), so they get their own shadow applied at construction time (see
# dashboard.py's _card()) rather than here, where a one-time findChildren
# pass would only ever catch the very first set built.
_SHADOWED_FRAME_NAMES = {"Panel", "Sidebar", "ContextPanel", "TopBar"}

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

# Icon-only sidebar (ui.widgets.nav_icons): one glyph kind per real NAV_ITEMS
# screen -- 14 items, not the design handoff's 6, since Spiced actually has
# 14 screens and every one needs to stay reachable.
_NAV_ICON_KINDS = {
    "Dashboard": "dashboard",
    "Projects": "projects",
    "Debugging Buddy": "debugging",
    "Automated Testing": "testing",
    "Feedback Review": "feedback",
    "Marketing": "marketing",
    "Business": "business",
    "Art": "art",
    "Audio": "audio",
    "Animation": "animation",
    "Shaders/VFX": "shaders_vfx",
    "Team": "team",
    "Roadmap": "roadmap",
    "Settings": "settings",
}

_DASHBOARD_INDEX = 0


class MainWindow(QWidget):
    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        # Registered before any child widget is built below -- PillButton and
        # NavOrbButton (built at ~100 call sites across every screen) resolve
        # their splash's reduced_motion check through this rather than
        # needing Services threaded through their own constructors.
        set_active_services(services)
        self.setObjectName("Root")
        self.setWindowTitle("Spiced")
        self.resize(1180, 760)
        self.setMinimumSize(920, 600)
        # Frutiger Aqua theme (ui.theme): lets the #Root QSS rule (a plain
        # sunset gradient, solid white in the high-contrast palette) paint
        # -- a plain QWidget subclass doesn't auto-paint a stylesheet
        # background otherwise. OceanBackgroundWidget below normally covers
        # this entirely with its own richer scene; this QSS rule is what
        # shows through instead when that widget hides itself for
        # high-contrast (see OceanBackgroundWidget.refresh_accessibility_state).
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Ocean background scene (island, waves, orbs, wind, mouse
        # parallax) -- sits behind the top bar/sidebar/workspace/context
        # panel row built below, added first and explicitly lowered so
        # creation order never matters. Resized to fill the window in
        # resizeEvent; fed live mouse position via the QApplication-wide
        # event filter installed below, since the panels above it cover
        # nearly the whole window and would otherwise swallow most mouse
        # moves before this widget's own mouseMoveEvent ever saw them.
        self._background = OceanBackgroundWidget(self._services, self)
        self._background.setGeometry(self.rect())
        self._background.lower()
        QApplication.instance().installEventFilter(self)

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

        # Keyboard Shortcuts for Power Users (Phase L, Phase 2 tier): the
        # Command Palette's own Ctrl+K trigger becomes one managed action
        # ("command_palette") below rather than a separate, disconnected
        # QShortcut, so rebinding it in Settings actually changes the real
        # trigger too -- see core.keyboard_shortcuts and _setup_keyboard_shortcuts.
        self._cheat_sheet = ShortcutsCheatSheet(self._current_shortcut_bindings, self)
        self._shortcuts: dict[str, QShortcut] = {}
        self._setup_keyboard_shortcuts()
        self._settings_screen.settings_changed.connect(self._setup_keyboard_shortcuts)

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

        self._apply_glass_elevation()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._background.setGeometry(self.rect())
        super().resizeEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        """Feeds the ocean background's mouse parallax from every mouse
        move in the app, not just ones MainWindow's own mouseMoveEvent
        would see. The sidebar/workspace/context-panel row covers nearly
        the whole window, and (without setMouseTracking enabled on every
        one of them) a plain child widget only receives move events while
        a button is held -- an application-wide filter is simpler and more
        reliable than chasing that down across ~20 widget classes. Ignores
        moves outside this window (e.g. while a dialog has focus) rather
        than tracking those too.
        """
        if event.type() == QEvent.Type.MouseMove:
            local = self.mapFromGlobal(event.globalPosition().toPoint())
            if self.rect().contains(local) and self.width() and self.height():
                x = local.x() / self.width() * 2 - 1
                y = local.y() / self.height() * 2 - 1
                self._background.set_mouse_norm(x, y)
        return super().eventFilter(watched, event)

    def _apply_glass_elevation(self) -> None:
        """Real drop-shadow elevation on the glass panels/cards -- Qt QSS has
        no ``box-shadow`` (see ui.theme's module docstring), so this is done
        in code instead, in one central place rather than touching every one
        of the 14 screen files that build a #Card."""
        for frame in self.findChildren(QFrame):
            if frame.objectName() not in _SHADOWED_FRAME_NAMES:
                continue
            shadow = QGraphicsDropShadowEffect(frame)
            shadow.setBlurRadius(24)
            shadow.setOffset(0, 6)
            shadow.setColor(QColor(20, 10, 40, 90))
            frame.setGraphicsEffect(shadow)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._build_scheduler.stop()
        self._top_bar.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
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

    # --- Keyboard Shortcuts for Power Users (Phase L, Phase 2 tier) --------

    def _current_shortcut_bindings(self) -> dict[str, str]:
        return load_bindings(self._services.keyboard_shortcuts_json())

    def _shortcut_action_callbacks(self) -> dict[str, object]:
        """action id -> zero-arg callable, for every action this window
        actually knows how to perform. ``run_tests``/``open_chatbox`` are
        scoped down to *navigating* to the relevant screen rather than also
        triggering that screen's Run/Analyze button -- doing the latter
        safely from a window-global shortcut would need every target screen
        to expose a stable "run my primary action" hook, which none do
        today; navigating there is one click from actually running it.
        """
        callbacks: dict[str, object] = {
            "command_palette": self._command_palette.open,
            "cheat_sheet": self._cheat_sheet.open,
            "next_project": lambda: self._cycle_active_project(1),
            "previous_project": lambda: self._cycle_active_project(-1),
        }
        if "Automated Testing" in NAV_ITEMS:
            index = NAV_ITEMS.index("Automated Testing")
            callbacks["run_tests"] = lambda i=index: self._stack.setCurrentIndex(i)
        if "Debugging Buddy" in NAV_ITEMS:
            index = NAV_ITEMS.index("Debugging Buddy")
            callbacks["open_chatbox"] = lambda i=index: self._stack.setCurrentIndex(i)
        for action in ACTIONS:
            if not action.id.startswith("goto_"):
                continue
            page_label = action.label.removeprefix("Go to ")
            if page_label in NAV_ITEMS:
                index = NAV_ITEMS.index(page_label)
                callbacks[action.id] = lambda i=index: self._stack.setCurrentIndex(i)
        return callbacks

    def _setup_keyboard_shortcuts(self) -> None:
        """(Re)build every managed QShortcut from the currently-saved
        bindings -- called once at startup and again whenever Settings
        saves a rebind, so a customized shortcut takes effect immediately,
        no restart needed."""
        for shortcut in self._shortcuts.values():
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._shortcuts = {}

        bindings = self._current_shortcut_bindings()
        callbacks = self._shortcut_action_callbacks()
        for action in ACTIONS:
            callback = callbacks.get(action.id)
            if callback is None:
                continue
            sequence = binding_for(action.id, bindings)
            if not sequence:
                continue
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts[action.id] = shortcut

    def _cycle_active_project(self, direction: int) -> None:
        projects = self._services.projects.list_projects()
        if not projects:
            return
        active = self._services.active_project()
        ids = [p.id for p in projects]
        try:
            index = ids.index(active.id) if active is not None else -1
        except ValueError:
            index = -1
        target = projects[(index + direction) % len(projects)]
        self._switch_active_project(target.id)

    def _build_sidebar(self) -> QFrame:
        """84px icon-only rail (design handoff) -- the wordmark/tagline move
        to the top bar (see ui.top_bar.TopBar, which already shows "Spiced"),
        since there's no room for them here. The icon list itself sits in a
        QScrollArea so all 14 real screens (vs. the handoff's 6) stay
        reachable at the app's minimum window height without clipping."""
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(84)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 18, 0, 14)
        layout.setSpacing(14)

        layout.addWidget(MascotLogo(38), 0, Qt.AlignmentFlag.AlignHCenter)

        icon_column = QWidget()
        icon_layout = QVBoxLayout(icon_column)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(10)

        settings_index = NAV_ITEMS.index("Settings")
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[NavOrbButton] = []
        for index, name in enumerate(NAV_ITEMS):
            if index == settings_index:
                continue
            kind = _NAV_ICON_KINDS.get(name, "dashboard")
            btn = NavOrbButton(kind, name)
            btn.clicked.connect(lambda _checked, i=index: self._stack.setCurrentIndex(i))
            self._nav_group.addButton(btn, index)
            self._nav_buttons.append(btn)
            icon_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        icon_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(icon_column)
        layout.addWidget(scroll, 1)

        settings_btn = NavOrbButton("settings", "Settings", settings=True)
        settings_btn.clicked.connect(
            lambda _checked, i=settings_index: self._stack.setCurrentIndex(i)
        )
        self._nav_group.addButton(settings_btn, settings_index)
        self._nav_buttons.append(settings_btn)
        layout.addWidget(settings_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self._apply_nav_glyph_colors()
        return sidebar

    def _apply_nav_glyph_colors(self) -> None:
        """Keeps the custom-painted nav glyphs (ui.widgets.nav_icons, which
        QSS alone can't reach) in sync with whichever accessibility palette
        is currently active -- called once at startup and again whenever
        Settings saves an accessibility change (see __init__)."""
        palette = theme.resolve_palette(
            high_contrast=self._services.accessibility_high_contrast_enabled(),
            colorblind_safe=self._services.accessibility_colorblind_safe_enabled(),
        )
        idle = palette["TEXT_ON_DARK"]
        active = palette["NAV_ACTIVE_TEXT"]
        settings_idle = palette["NEUTRAL_TEXT"]
        for btn in self._nav_buttons:
            if btn.objectName() == "NavButtonSettings":
                btn.set_glyph_colors(settings_idle, active)
            else:
                btn.set_glyph_colors(idle, active)

    def _build_workspace(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(6, 6, 6, 6)

        self._stack = FadeStackedWidget(services=self._services)

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
        # Accessibility text-size/high-contrast/colorblind-safe toggles swap
        # the whole QSS palette live (see ui.theme) -- the sidebar's
        # custom-painted nav glyphs can't pick that up from QSS alone, so
        # they're re-tinted explicitly here too.
        self._settings_screen.settings_changed.connect(self._apply_nav_glyph_colors)
        # Same reason: Reduce Motion and high-contrast both change how (or
        # whether) the ocean background paints itself.
        self._settings_screen.settings_changed.connect(
            self._background.refresh_accessibility_state
        )
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
