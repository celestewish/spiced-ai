"""Settings: AI provider, mock plan, Team Mode toggle, and a connection test."""

from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QMessageBox,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.ai import available_providers, build_provider
from spiced.app.services import Services
from spiced.automation.finding import SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING
from spiced.core.keyboard_shortcuts import (
    ACTIONS as SHORTCUT_ACTIONS,
)
from spiced.core.keyboard_shortcuts import (
    binding_for,
    dump_bindings,
    load_bindings,
    reset_binding,
)
from spiced.core.notification_routing import (
    DEFAULT_EVENT_KIND_DISCIPLINES,
    KNOWN_EVENT_KINDS,
    disciplines_for_event,
)
from spiced.backend_client.config import backend_unreachable_message
from spiced.core.plans import PLANS
from spiced.core.rules_engine import (
    ACTION_CREATE_TASK,
    ACTION_NOTIFY,
    ACTION_QUEUE_CHANGELOG_NOTE,
)
from spiced.ui.auth_dialog import AuthDialog
from spiced.ui.screens.team import SUGGESTED_DISCIPLINES
from spiced.ui.theme import TEXT_SIZES, build_stylesheet
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.scroll_safe_combo_box import ScrollSafeComboBox


def _hairline() -> QFrame:
    line = QFrame()
    line.setObjectName("Hairline")
    line.setFixedHeight(1)
    return line


class _RoutingLoadWorker(QObject):
    done = Signal(object, list)  # team_id | None, list[EventRoutingRule]
    failed = Signal(str)

    def __init__(self, services: Services, project_uuid: str) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid

    def run(self) -> None:
        try:
            team = self._services.teams.find_team_for_project(self._project_uuid)
            if team is None:
                self.done.emit(None, [])
                return
            rules = self._services.teams.list_routing_rules(team.id)
            self.done.emit(team.id, rules)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't load routing rules: {exc}")


class _RoutingMutateWorker(QObject):
    done = Signal()
    failed = Signal(str)

    def __init__(self, action) -> None:
        super().__init__()
        self._action = action

    def run(self) -> None:
        try:
            self._action()
            self.done.emit()
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"That didn't go through: {exc}")


class _PreferencesLoadWorker(QObject):
    """Loads the signed-in user's own notification preferences for the
    active project's team -- Phase K's Notification settings section builds
    directly on Phase J's routing panel above, so this mirrors
    ``_RoutingLoadWorker`` exactly, just filtered to "mine only" (routing
    rules are team-wide; preferences are per-member)."""

    done = Signal(object, list)  # team_id | None, list[NotificationPreference] (mine only)
    failed = Signal(str)

    def __init__(self, services: Services, project_uuid: str) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid

    def run(self) -> None:
        try:
            team = self._services.teams.find_team_for_project(self._project_uuid)
            if team is None:
                self.done.emit(None, [])
                return
            all_prefs = self._services.teams.list_notification_preferences(team.id)
            user = self._services.auth.current_user()
            mine = [p for p in all_prefs if user and p.user_id == user.id]
            self.done.emit(team.id, mine)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't load notification preferences: {exc}")


class _TriggerRulesLoadWorker(QObject):
    """Loads the active project's team's Cross-Feature Rules Engine rules
    (Market-Viability Roadmap, Phase 4) -- mirrors ``_RoutingLoadWorker``
    exactly; ``_RoutingMutateWorker`` below is reused as-is for add/delete,
    since it just runs whatever callable it's given."""

    done = Signal(object, list)  # team_id | None, list[TriggerRule]
    failed = Signal(str)

    def __init__(self, services: Services, project_uuid: str) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid

    def run(self) -> None:
        try:
            team = self._services.teams.find_team_for_project(self._project_uuid)
            if team is None:
                self.done.emit(None, [])
                return
            rules = self._services.teams.list_trigger_rules(team.id)
            self.done.emit(team.id, rules)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't load automation rules: {exc}")


class _SubscriptionLoadWorker(QObject):
    """Loads the signed-in user's real Stripe subscription (Market-
    Viability Roadmap, Phase 5) -- BillingService.current_subscription is
    already a safe no-op returning None for a solo/offline user, so this
    worker never needs a "not signed in" branch of its own."""

    done = Signal(object)  # Subscription | None
    failed = Signal(str)

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services

    def run(self) -> None:
        try:
            self.done.emit(self._services.billing.current_subscription())
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't load subscription status: {exc}")


class _BillingActionWorker(QObject):
    """Runs one billing action (start a checkout, open the portal) and
    hands back the Stripe-hosted URL to open in the system browser --
    mirrors _RoutingMutateWorker's "just run whatever callable" shape."""

    done = Signal(str)
    failed = Signal(str)

    def __init__(self, action) -> None:
        super().__init__()
        self._action = action

    def run(self) -> None:
        try:
            self.done.emit(self._action())
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"That didn't go through: {exc}")


class SettingsScreen(QWidget):
    settings_changed = Signal()

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
        content.setObjectName("ScrollContent")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)

        # AI provider (OpenAI is the default; mock is free/offline; Gemini optional)
        self._provider_box = ScrollSafeComboBox()
        self._provider_box.addItems(available_providers())
        self._provider_box.setCurrentText(self._services.provider_name())
        self._provider_box.currentTextChanged.connect(self._on_provider_changed)
        form.addRow("AI provider", self._provider_box)

        # Preview plan, solo/offline only -- see the Billing section below
        # for the real plan a signed-in user gets from their own Stripe
        # subscription (Market-Viability Roadmap, Phase 5).
        self._plan_box = ScrollSafeComboBox()
        for plan in PLANS.values():
            self._plan_box.addItem(plan.label, plan.key)
        current_key = self._services.usage.current_plan().key
        idx = self._plan_box.findData(current_key)
        if idx >= 0:
            self._plan_box.setCurrentIndex(idx)
        self._plan_box.currentIndexChanged.connect(self._on_plan_changed)
        form.addRow("Preview plan (solo)", self._plan_box)

        layout.addLayout(form)

        note = QLabel(
            "This preview plan is for exploring the tiers while working solo/offline -- pick "
            "any of them for free, no payment or account involved. Once signed in to "
            "Small-Team Mode, your real plan (below) takes over and this preview no longer "
            "applies."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._build_billing_section(layout)

        # Solo-Dev Mode vs. Small-Team Mode (off/solo by default)
        layout.addWidget(_hairline())
        team_title = QLabel("Team")
        team_title.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(team_title)

        self._team_mode_toggle = QCheckBox("Small-Team Mode")
        self._team_mode_toggle.setChecked(self._services.team_mode_enabled())
        self._team_mode_toggle.toggled.connect(self._on_team_mode_toggled)
        layout.addWidget(self._team_mode_toggle)

        team_note = QLabel(
            "Solo-Dev Mode (default): everything stays local, prompts stay short and "
            "prioritized. Small-Team Mode: when the active project is linked to a team "
            "(Projects screen), AI replies may also suggest which teammate a finding could "
            "be routed to — always as text in the reply, never an action Spiced takes on "
            "its own."
        )
        team_note.setObjectName("Muted")
        team_note.setWordWrap(True)
        layout.addWidget(team_note)

        # Opt-In Only Telemetry (off by default). Mirrors the Community
        # Pulse opt-in pattern exactly (settings.py's community_pulse
        # checkbox / services.community_pulse_enabled()).
        layout.addWidget(_hairline())
        telemetry_title = QLabel("Privacy")
        telemetry_title.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(telemetry_title)

        self._telemetry_toggle = QCheckBox("Help improve Spiced")
        self._telemetry_toggle.setChecked(self._services.telemetry_opt_in_enabled())
        self._telemetry_toggle.toggled.connect(self._on_telemetry_toggled)
        layout.addWidget(self._telemetry_toggle)

        telemetry_note = QLabel(
            "Off by default. If you turn this on, Spiced sends anonymous counts of which "
            "features you use — for example, a bare event name like \"Debugging Buddy: "
            "crash diagnosis run\" plus a timestamp. Nothing else is attached: never your "
            "code, logs, file paths, feedback content, or any project/game content, and "
            "never your account, email, or user id, even if you're signed in above for "
            "Small-Team Mode. A random anonymous id (not tied to you) is generated once on "
            "this machine so events can be counted without identifying you."
        )
        telemetry_note.setObjectName("Muted")
        telemetry_note.setWordWrap(True)
        layout.addWidget(telemetry_note)

        # Discord/Community Bot Integration: posting (Phase G, section 7).
        # Deliberately a separate toggle from Community Pulse above — that's
        # opt-in *read*, this is opt-in *write*, a meaningfully bigger trust
        # boundary (see core.community.discord_poster).
        layout.addWidget(_hairline())
        discord_title = QLabel("Discord integration")
        discord_title.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(discord_title)

        self._discord_toggle = QCheckBox("Allow Spiced to post to Discord")
        self._discord_toggle.setChecked(self._services.discord_posting_enabled())
        self._discord_toggle.toggled.connect(self._on_discord_toggled)
        layout.addWidget(self._discord_toggle)

        discord_note = QLabel(
            "Off by default. Uses the same DISCORD_BOT_TOKEN as Community Pulse, plus "
            "DISCORD_CHANNEL_ID as the post target (or a separate DISCORD_ANNOUNCE_CHANNEL_ID, "
            "if set). Even when this is on, Spiced always shows you the exact text before "
            "posting and requires a click to send — unless you also turn on the auto-post "
            "option below, which skips that confirmation."
        )
        discord_note.setObjectName("Muted")
        discord_note.setWordWrap(True)
        layout.addWidget(discord_note)

        self._discord_auto_post_toggle = QCheckBox(
            "Post automatically without asking (skips the confirm step)"
        )
        self._discord_auto_post_toggle.setChecked(self._services.discord_auto_post_enabled())
        self._discord_auto_post_toggle.toggled.connect(self._on_discord_auto_post_toggled)
        layout.addWidget(self._discord_auto_post_toggle)

        # Rapid Prototyping Mode (Phase H, section 7 part 2, Core tier). Off
        # by default, same opt-in shape as Team Mode above.
        layout.addWidget(_hairline())
        prototype_title = QLabel("Prototyping")
        prototype_title.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(prototype_title)

        self._prototype_mode_toggle = QCheckBox("Rapid Prototyping Mode")
        self._prototype_mode_toggle.setChecked(self._services.prototype_mode_enabled())
        self._prototype_mode_toggle.toggled.connect(self._on_prototype_mode_toggled)
        layout.addWidget(self._prototype_mode_toggle)

        prototype_note = QLabel(
            "Off by default. When on, the Automated Testing screen foregrounds a minimal "
            "\"Quick Smoke Test\" check-in (does this idea work at all?) and de-emphasizes the "
            "full functional/performance/accessibility/economy QA suite below it — nothing is "
            "removed, everything stays reachable, only what's foregrounded changes. Meant for "
            "game-jam and early-prototype work where deep testing isn't the point yet."
        )
        prototype_note.setObjectName("Muted")
        prototype_note.setWordWrap(True)
        layout.addWidget(prototype_note)

        layout.addWidget(_hairline())
        self._build_accessibility_section(layout)
        self._build_keyboard_shortcuts_section(layout)
        self._build_notification_routing_section(layout)
        self._build_notification_preferences_section(layout)
        self._build_automation_rules_section(layout)

        # Connection test for the selected provider
        layout.addWidget(_hairline())
        test_title = QLabel("Connection test")
        test_title.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(test_title)

        test_desc = QLabel(
            "Sends one short, fixed prompt to your selected provider to confirm it's "
            "set up. With OpenAI, this uses your OPENAI_API_KEY. No project files are "
            "included."
        )
        test_desc.setObjectName("Muted")
        test_desc.setWordWrap(True)
        layout.addWidget(test_desc)

        row = QHBoxLayout()
        self._test_btn = PillButton("Send test prompt", ghost=True)
        self._test_btn.clicked.connect(self._on_test)
        row.addWidget(self._test_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._test_result = QLabel("")
        self._test_result.setObjectName("Muted")
        self._test_result.setWordWrap(True)
        layout.addWidget(self._test_result)

        layout.addStretch(1)

        self._routing_team_id: str | None = None
        self._pref_team_id: str | None = None
        self._trigger_rules_team_id: str | None = None
        self._billing_subscription = None
        self.refresh()

    def _on_provider_changed(self, name: str) -> None:
        self._services.set_provider_name(name)
        self.settings_changed.emit()

    def _on_team_mode_toggled(self, checked: bool) -> None:
        if checked and not self._services.auth.is_logged_in():
            if not self._services.auth.is_configured():
                QMessageBox.information(
                    self,
                    "Team Mode not configured",
                    "Set SUPABASE_URL and SUPABASE_ANON_KEY in your environment or a local "
                    ".env file to use Team Mode.",
                )
                self._team_mode_toggle.blockSignals(True)
                self._team_mode_toggle.setChecked(False)
                self._team_mode_toggle.blockSignals(False)
                return
            dialog = AuthDialog(self._services.auth, self)
            if dialog.exec() != AuthDialog.DialogCode.Accepted:
                self._team_mode_toggle.blockSignals(True)
                self._team_mode_toggle.setChecked(False)
                self._team_mode_toggle.blockSignals(False)
                return
        self._services.set_team_mode_enabled(checked)
        self.settings_changed.emit()

    def _on_prototype_mode_toggled(self, checked: bool) -> None:
        self._services.set_prototype_mode_enabled(checked)
        self.settings_changed.emit()

    def _on_telemetry_toggled(self, checked: bool) -> None:
        self._services.set_telemetry_opt_in_enabled(checked)
        self.settings_changed.emit()

    def _on_discord_toggled(self, checked: bool) -> None:
        self._services.set_discord_posting_enabled(checked)
        self.settings_changed.emit()

    def _on_discord_auto_post_toggled(self, checked: bool) -> None:
        self._services.set_discord_auto_post_enabled(checked)
        self.settings_changed.emit()

    def _on_plan_changed(self, _index: int) -> None:
        self._services.usage.set_plan(self._plan_box.currentData())
        self.settings_changed.emit()

    # --- In-App Accessibility Settings (Phase L, Core tier) -----------------
    #
    # All four controls apply live -- the stylesheet is rebuilt and
    # reapplied to the running QApplication immediately (see
    # ``_apply_accessibility_stylesheet``), no restart needed. Motion
    # reduction is read by ``ui.effects.motion.reduced_motion`` -- every
    # animation added under ``ui.effects`` (PillButton/NavOrbButton's click
    # splash so far; tab-fade transitions and the background scene are
    # landing in later PRs) checks it before starting and skips straight to
    # its end state when it's on.

    # --- Billing: real Stripe subscription (Market-Viability Roadmap, Phase
    # 5) ----------------------------------------------------------------
    #
    # The desktop app never touches a card number -- "Subscribe"/"Manage
    # subscription" both open a Stripe-hosted page in the system browser
    # (QDesktopServices.openUrl) and this screen finds out what happened by
    # re-fetching status afterward, not via any callback into the app.

    def _build_billing_section(self, layout: QVBoxLayout) -> None:
        layout.addWidget(_hairline())
        heading = QLabel("Billing")
        heading.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(heading)

        note = QLabel(
            "Your real plan once signed in to Small-Team Mode, backed by an actual Stripe "
            "subscription (test mode only -- no real card is ever charged in this build). "
            "Spiced never sees or stores your card details; Subscribe and Manage subscription "
            "both open Stripe's own secure page in your browser."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._billing_status = QLabel("")
        self._billing_status.setObjectName("Muted")
        self._billing_status.setWordWrap(True)
        layout.addWidget(self._billing_status)

        row = QHBoxLayout()
        self._billing_plan_box = ScrollSafeComboBox()
        for plan in PLANS.values():
            if plan.key != "free":  # nothing to check out for the free tier
                self._billing_plan_box.addItem(plan.label, plan.key)
        row.addWidget(self._billing_plan_box, 1)
        self._billing_subscribe_btn = PillButton("Subscribe")
        self._billing_subscribe_btn.clicked.connect(self._on_subscribe)
        row.addWidget(self._billing_subscribe_btn)
        self._billing_manage_btn = PillButton("Manage subscription", ghost=True)
        self._billing_manage_btn.clicked.connect(self._on_manage_subscription)
        row.addWidget(self._billing_manage_btn)
        self._billing_refresh_btn = PillButton("Refresh status", ghost=True)
        self._billing_refresh_btn.clicked.connect(self._refresh_billing)
        row.addWidget(self._billing_refresh_btn)
        layout.addLayout(row)

    def _refresh_billing(self) -> None:
        if not self._services.auth.is_logged_in():
            self._billing_subscription = None
            self._billing_status.setText(
                "Sign in to Small-Team Mode (below) to see and manage a real subscription."
            )
            self._billing_subscribe_btn.setEnabled(False)
            self._billing_manage_btn.setEnabled(False)
            return

        self._billing_status.setText("Loading…")
        self._billing_subscribe_btn.setEnabled(False)
        self._billing_manage_btn.setEnabled(False)
        worker = _SubscriptionLoadWorker(self._services)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_billing_loaded)
        worker.failed.connect(self._on_billing_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_billing_loaded(self, subscription) -> None:
        self._billing_subscription = subscription
        self._billing_manage_btn.setEnabled(subscription is not None)
        self._billing_subscribe_btn.setEnabled(True)
        if subscription is None:
            self._billing_status.setText("No subscription yet -- pick a plan and Subscribe.")
        elif subscription.is_usable:
            plan = PLANS.get(subscription.plan_key)
            label = plan.label if plan else subscription.plan_key
            self._billing_status.setText(f"{label} plan -- {subscription.status}.")
        else:
            self._billing_status.setText(
                f"Subscription {subscription.status} -- Manage subscription to resolve it, "
                "or Subscribe to start a new one."
            )

    def _on_billing_failed(self, message: str) -> None:
        self._billing_status.setText(message)
        self._billing_subscribe_btn.setEnabled(True)

    def _on_subscribe(self) -> None:
        plan_key = self._billing_plan_box.currentData()
        if not plan_key:
            return
        self._billing_subscribe_btn.setEnabled(False)
        worker = _BillingActionWorker(lambda: self._services.billing.start_checkout(plan_key))
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_billing_url_ready)
        worker.failed.connect(self._on_billing_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_manage_subscription(self) -> None:
        self._billing_manage_btn.setEnabled(False)
        worker = _BillingActionWorker(self._services.billing.open_billing_portal)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_billing_url_ready)
        worker.failed.connect(self._on_billing_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_billing_url_ready(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))
        self._billing_status.setText(
            "Opened in your browser. Come back here and click Refresh status once you're done."
        )
        self._billing_subscribe_btn.setEnabled(True)
        self._billing_manage_btn.setEnabled(self._billing_subscription is not None)

    def _build_accessibility_section(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Accessibility")
        heading.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(heading)

        note = QLabel(
            "Applies immediately across Spiced's own UI -- no restart needed. Text size and "
            "the high-contrast / colorblind-safe palettes make real, measurable changes to the "
            "stylesheet (see ui.theme). Motion reduction turns off button click splashes and "
            "any other animation Spiced adds going forward."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self._text_size_box = ScrollSafeComboBox()
        for size_key in TEXT_SIZES:
            self._text_size_box.addItem(size_key.capitalize(), size_key)
        idx = self._text_size_box.findData(self._services.accessibility_text_size())
        if idx >= 0:
            self._text_size_box.setCurrentIndex(idx)
        self._text_size_box.currentIndexChanged.connect(self._on_text_size_changed)
        form.addRow("Text size", self._text_size_box)
        layout.addLayout(form)

        self._high_contrast_toggle = QCheckBox("High-contrast palette")
        self._high_contrast_toggle.setChecked(self._services.accessibility_high_contrast_enabled())
        self._high_contrast_toggle.toggled.connect(self._on_high_contrast_toggled)
        layout.addWidget(self._high_contrast_toggle)

        self._colorblind_safe_toggle = QCheckBox("Colorblind-safe palette")
        self._colorblind_safe_toggle.setChecked(
            self._services.accessibility_colorblind_safe_enabled()
        )
        self._colorblind_safe_toggle.toggled.connect(self._on_colorblind_safe_toggled)
        layout.addWidget(self._colorblind_safe_toggle)

        palette_note = QLabel(
            "If both are on, high-contrast takes priority -- it's the stronger accessibility "
            "need and its near-black-on-white values already read clearly under color vision "
            "deficiency too."
        )
        palette_note.setObjectName("Muted")
        palette_note.setWordWrap(True)
        layout.addWidget(palette_note)

        self._reduce_motion_toggle = QCheckBox("Reduce motion")
        self._reduce_motion_toggle.setChecked(self._services.accessibility_reduce_motion_enabled())
        self._reduce_motion_toggle.toggled.connect(self._on_reduce_motion_toggled)
        layout.addWidget(self._reduce_motion_toggle)

    def _on_text_size_changed(self, _index: int) -> None:
        self._services.set_accessibility_text_size(self._text_size_box.currentData())
        self._apply_accessibility_stylesheet()
        self.settings_changed.emit()

    def _on_high_contrast_toggled(self, checked: bool) -> None:
        self._services.set_accessibility_high_contrast_enabled(checked)
        self._apply_accessibility_stylesheet()
        self.settings_changed.emit()

    def _on_colorblind_safe_toggled(self, checked: bool) -> None:
        self._services.set_accessibility_colorblind_safe_enabled(checked)
        self._apply_accessibility_stylesheet()
        self.settings_changed.emit()

    def _on_reduce_motion_toggled(self, checked: bool) -> None:
        self._services.set_accessibility_reduce_motion_enabled(checked)
        self.settings_changed.emit()

    def _apply_accessibility_stylesheet(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        app.setStyleSheet(
            build_stylesheet(
                text_size=self._services.accessibility_text_size(),
                high_contrast=self._services.accessibility_high_contrast_enabled(),
                colorblind_safe=self._services.accessibility_colorblind_safe_enabled(),
                reduce_motion=self._services.accessibility_reduce_motion_enabled(),
            )
        )

    # --- Keyboard Shortcuts for Power Users (Phase L, Phase 2 tier) --------
    #
    # Rebinding here saves a new action->key-sequence override
    # (core.keyboard_shortcuts); MainWindow rebuilds every QShortcut from
    # this screen's settings_changed signal, so a rebind (or reset) takes
    # effect immediately, no restart needed -- see
    # MainWindow._setup_keyboard_shortcuts.

    def _build_keyboard_shortcuts_section(self, layout: QVBoxLayout) -> None:
        layout.addWidget(_hairline())
        heading = QLabel("Keyboard shortcuts")
        heading.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(heading)

        note = QLabel(
            "Press \"?\" anywhere to see the full cheat sheet. Pick an action below, click into "
            "the box and press your new key combination, then Save -- or Reset to go back to "
            "its default."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._shortcuts_list = QTextEdit()
        self._shortcuts_list.setReadOnly(True)
        self._shortcuts_list.setFixedHeight(150)
        layout.addWidget(self._shortcuts_list)

        row = QHBoxLayout()
        self._shortcut_action_box = ScrollSafeComboBox()
        for action in SHORTCUT_ACTIONS:
            self._shortcut_action_box.addItem(action.label, action.id)
        self._shortcut_action_box.currentIndexChanged.connect(self._on_shortcut_action_changed)
        row.addWidget(self._shortcut_action_box, 1)

        self._shortcut_edit = QKeySequenceEdit()
        row.addWidget(self._shortcut_edit, 1)

        save_btn = PillButton("Save binding")
        save_btn.clicked.connect(self._on_save_shortcut)
        row.addWidget(save_btn)

        reset_btn = PillButton("Reset to default", ghost=True)
        reset_btn.clicked.connect(self._on_reset_shortcut)
        row.addWidget(reset_btn)
        layout.addLayout(row)

        self._on_shortcut_action_changed(0)
        self._refresh_shortcuts_list()

    def _current_bindings(self) -> dict[str, str]:
        return load_bindings(self._services.keyboard_shortcuts_json())

    def _refresh_shortcuts_list(self) -> None:
        bindings = self._current_bindings()
        lines = [f"{binding_for(a.id, bindings)}   —   {a.label}" for a in SHORTCUT_ACTIONS]
        self._shortcuts_list.setPlainText("\n".join(lines))

    def _on_shortcut_action_changed(self, _index: int) -> None:
        action_id = self._shortcut_action_box.currentData()
        if not action_id:
            return
        bindings = self._current_bindings()
        self._shortcut_edit.setKeySequence(QKeySequence(binding_for(action_id, bindings)))

    def _on_save_shortcut(self) -> None:
        action_id = self._shortcut_action_box.currentData()
        if not action_id:
            return
        sequence = self._shortcut_edit.keySequence().toString()
        if not sequence:
            QMessageBox.information(
                self, "No key combination", "Press a key combination in the box first."
            )
            return
        bindings = self._current_bindings()
        bindings[action_id] = sequence
        self._services.set_keyboard_shortcuts_json(dump_bindings(bindings))
        self._refresh_shortcuts_list()
        self.settings_changed.emit()

    def _on_reset_shortcut(self) -> None:
        action_id = self._shortcut_action_box.currentData()
        if not action_id:
            return
        bindings = reset_binding(self._current_bindings(), action_id)
        self._services.set_keyboard_shortcuts_json(dump_bindings(bindings))
        self._on_shortcut_action_changed(self._shortcut_action_box.currentIndex())
        self._refresh_shortcuts_list()
        self.settings_changed.emit()

    # --- Relevance-Based Notifications: routing config (Phase J, #6) --------
    #
    # Scope boundary: this only edits the ROUTING rules (which discipline(s)
    # an event kind routes to) plus shows the default mapping. The actual
    # inbox (bell icon + dropdown) is the Notification Center's UI (Phase K,
    # section 9 part 1) in the top bar -- see ui.top_bar.TopBar and
    # ui.notification_center. Only usable for a team-linked active project,
    # since routing rules are saved per-team.

    def _build_notification_routing_section(self, layout: QVBoxLayout) -> None:
        layout.addWidget(_hairline())
        heading = QLabel("Notification routing")
        heading.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(heading)

        note = QLabel(
            "Which discipline(s) each kind of event routes to -- the decision layer the "
            "Notification Center (bell icon, top bar) uses to decide who to notify. This only "
            "edits the routing rules for the active project's team; pick real-time vs. digest "
            "delivery for yourself below."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._routing_status = QLabel("")
        self._routing_status.setObjectName("Muted")
        self._routing_status.setWordWrap(True)
        layout.addWidget(self._routing_status)

        self._routing_list = QTextEdit()
        self._routing_list.setReadOnly(True)
        self._routing_list.setFixedHeight(120)
        layout.addWidget(self._routing_list)

        row = QHBoxLayout()
        self._routing_event_box = ScrollSafeComboBox()
        self._routing_event_box.addItems(KNOWN_EVENT_KINDS)
        row.addWidget(self._routing_event_box, 1)
        self._routing_discipline_box = ScrollSafeComboBox()
        self._routing_discipline_box.setEditable(True)
        self._routing_discipline_box.addItems(SUGGESTED_DISCIPLINES)
        row.addWidget(self._routing_discipline_box, 1)
        self._routing_add_btn = PillButton("Add rule")
        self._routing_add_btn.clicked.connect(self._on_add_routing_rule)
        row.addWidget(self._routing_add_btn)
        layout.addLayout(row)

    # --- Notification Center: digest options (Phase K, section 9 part 1) ----
    #
    # Builds directly on the routing panel above rather than replacing it:
    # routing decides WHETHER an event kind is relevant to you at all (by
    # discipline, or your own enabled/disabled override); this section only
    # decides WHEN a relevant one actually surfaces -- real-time, or held
    # for an hourly/daily digest (see core.notification_center.
    # bucket_by_cadence, which the bell's poller applies).

    def _build_notification_preferences_section(self, layout: QVBoxLayout) -> None:
        layout.addWidget(_hairline())
        heading = QLabel("Notification settings")
        heading.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(heading)

        note = QLabel(
            "Choose how you want to hear about each kind of event once it's relevant to you "
            "(see the routing rules above): Real-time (as soon as it happens), Hourly digest, "
            "or Daily digest. You can also enable/disable an event kind for yourself here, "
            "overriding the discipline-based default regardless of your own discipline. Only "
            "usable for a team-linked project you're signed in for."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._pref_status = QLabel("")
        self._pref_status.setObjectName("Muted")
        self._pref_status.setWordWrap(True)
        layout.addWidget(self._pref_status)

        self._pref_list = QTextEdit()
        self._pref_list.setReadOnly(True)
        self._pref_list.setFixedHeight(120)
        layout.addWidget(self._pref_list)

        row = QHBoxLayout()
        self._pref_event_box = ScrollSafeComboBox()
        self._pref_event_box.addItems(KNOWN_EVENT_KINDS)
        row.addWidget(self._pref_event_box, 1)
        self._pref_enabled_box = ScrollSafeComboBox()
        self._pref_enabled_box.addItem("Enabled", True)
        self._pref_enabled_box.addItem("Disabled", False)
        row.addWidget(self._pref_enabled_box, 1)
        self._pref_delivery_box = ScrollSafeComboBox()
        self._pref_delivery_box.addItems(["realtime", "hourly", "daily"])
        row.addWidget(self._pref_delivery_box, 1)
        self._pref_save_btn = PillButton("Save preference")
        self._pref_save_btn.clicked.connect(self._on_save_preference)
        row.addWidget(self._pref_save_btn)
        layout.addLayout(row)

    # --- Automation Rules: Cross-Feature Rules/Trigger Engine
    # (Market-Viability Roadmap, Phase 4) ------------------------------------
    #
    # Mirrors the routing panel's own list/add-rule/combo-box pattern above,
    # but decides WHAT HAPPENS for an event kind (create a task, notify,
    # queue a changelog note) rather than WHO gets notified -- see
    # core.rules_engine's module docstring. Only usable for a team-linked
    # active project, same restriction as routing rules, since rules are
    # saved per-team.

    def _build_automation_rules_section(self, layout: QVBoxLayout) -> None:
        layout.addWidget(_hairline())
        heading = QLabel("Automation rules")
        heading.setObjectName("SectionTitle")
        layout.addSpacing(6)
        layout.addWidget(heading)

        note = QLabel(
            "What happens when a Spiced feature flags something on this project's team: "
            "create a task, notify the relevant discipline, or queue a note for the next "
            "changelog draft. Without a rule here, every event kind quietly queues a "
            "changelog note by default -- create_task and notify only ever fire from an "
            "explicit rule below, since they need somewhere (a team) to go."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._trigger_rules_status = QLabel("")
        self._trigger_rules_status.setObjectName("Muted")
        self._trigger_rules_status.setWordWrap(True)
        layout.addWidget(self._trigger_rules_status)

        self._trigger_rules_list = QTextEdit()
        self._trigger_rules_list.setReadOnly(True)
        self._trigger_rules_list.setFixedHeight(120)
        layout.addWidget(self._trigger_rules_list)

        row = QHBoxLayout()
        self._trigger_event_box = ScrollSafeComboBox()
        self._trigger_event_box.addItems(KNOWN_EVENT_KINDS)
        row.addWidget(self._trigger_event_box, 1)
        self._trigger_severity_box = ScrollSafeComboBox()
        self._trigger_severity_box.addItems([SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR])
        self._trigger_severity_box.setCurrentText(SEVERITY_WARNING)
        row.addWidget(self._trigger_severity_box, 1)
        self._trigger_action_box = ScrollSafeComboBox()
        self._trigger_action_box.addItems(
            [ACTION_CREATE_TASK, ACTION_NOTIFY, ACTION_QUEUE_CHANGELOG_NOTE]
        )
        row.addWidget(self._trigger_action_box, 1)
        self._trigger_add_btn = PillButton("Add rule")
        self._trigger_add_btn.clicked.connect(self._on_add_trigger_rule)
        row.addWidget(self._trigger_add_btn)
        layout.addLayout(row)

    def refresh(self) -> None:
        """Reload the notification routing + preferences panels for the
        active project's team, if any. Safe to call whenever the active
        project changes."""
        self._refresh_billing()  # user-scoped, not project-scoped -- always safe to reload
        project = self._services.active_project()
        if project is None or not project.project_uuid or not self._services.auth.is_logged_in():
            self._routing_team_id = None
            self._routing_status.setText(
                "Only available for a team-linked project you're signed in for -- select one on "
                "the Projects screen."
            )
            self._routing_list.setPlainText("")
            self._routing_add_btn.setEnabled(False)

            self._pref_team_id = None
            self._pref_status.setText(
                "Only available for a team-linked project you're signed in for."
            )
            self._pref_list.setPlainText("")
            self._pref_save_btn.setEnabled(False)

            self._trigger_rules_team_id = None
            self._trigger_rules_status.setText(
                "Only available for a team-linked project you're signed in for -- select one on "
                "the Projects screen."
            )
            self._trigger_rules_list.setPlainText("")
            self._trigger_add_btn.setEnabled(False)
            return

        if not self._services.backend_reachable():
            # Same reachability cache Roadmap checks -- avoids each of the
            # three panels below independently discovering (and separately
            # reporting) that the backend isn't running.
            message = backend_unreachable_message()
            self._routing_team_id = None
            self._routing_status.setText(message)
            self._routing_list.setPlainText("")
            self._routing_add_btn.setEnabled(False)

            self._pref_team_id = None
            self._pref_status.setText(message)
            self._pref_list.setPlainText("")
            self._pref_save_btn.setEnabled(False)

            self._trigger_rules_team_id = None
            self._trigger_rules_status.setText(message)
            self._trigger_rules_list.setPlainText("")
            self._trigger_add_btn.setEnabled(False)
            return

        self._routing_add_btn.setEnabled(True)
        self._routing_status.setText("Loading…")
        worker = _RoutingLoadWorker(self._services, project.project_uuid)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_routing_loaded)
        worker.failed.connect(self._on_routing_load_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

        self._pref_save_btn.setEnabled(True)
        self._pref_status.setText("Loading…")
        pref_worker = _PreferencesLoadWorker(self._services, project.project_uuid)
        pref_thread = launch_worker(self, pref_worker)
        pref_thread.started.connect(pref_worker.run)
        pref_worker.done.connect(self._on_preferences_loaded)
        pref_worker.failed.connect(self._on_preferences_load_failed)
        pref_worker.done.connect(pref_thread.quit)
        pref_worker.failed.connect(pref_thread.quit)
        pref_thread.start()

        self._trigger_add_btn.setEnabled(True)
        self._trigger_rules_status.setText("Loading…")
        trigger_worker = _TriggerRulesLoadWorker(self._services, project.project_uuid)
        trigger_thread = launch_worker(self, trigger_worker)
        trigger_thread.started.connect(trigger_worker.run)
        trigger_worker.done.connect(self._on_trigger_rules_loaded)
        trigger_worker.failed.connect(self._on_trigger_rules_load_failed)
        trigger_worker.done.connect(trigger_thread.quit)
        trigger_worker.failed.connect(trigger_thread.quit)
        trigger_thread.start()

    def _on_routing_loaded(self, team_id: str | None, rules) -> None:
        self._routing_team_id = team_id
        if team_id is None:
            self._routing_status.setText(
                "This project isn't linked to a team yet -- link it on the Projects screen."
            )
            self._routing_list.setPlainText("")
            self._routing_add_btn.setEnabled(False)
            return
        self._routing_status.setText("")
        lines = []
        for event_kind in KNOWN_EVENT_KINDS:
            disciplines = disciplines_for_event(event_kind, rules)
            is_default = disciplines == DEFAULT_EVENT_KIND_DISCIPLINES.get(event_kind, [])
            suffix = " (default)" if is_default else " (customized)"
            shown = ", ".join(disciplines) if disciplines else "(none)"
            lines.append(f"{event_kind}: {shown}{suffix}")
        self._routing_list.setPlainText("\n".join(lines))

    def _on_routing_load_failed(self, message: str) -> None:
        self._routing_status.setText(message)

    def _on_add_routing_rule(self) -> None:
        if self._routing_team_id is None:
            return
        event_kind = self._routing_event_box.currentText()
        discipline = self._routing_discipline_box.currentText().strip()
        if not discipline:
            QMessageBox.information(self, "Missing discipline", "Pick or type a discipline first.")
            return
        team_id = self._routing_team_id
        self._routing_add_btn.setEnabled(False)

        worker = _RoutingMutateWorker(
            lambda: self._services.teams.add_routing_rule(team_id, event_kind, discipline)
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self.refresh)
        worker.failed.connect(self._on_routing_load_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_preferences_loaded(self, team_id: str | None, prefs) -> None:
        self._pref_team_id = team_id
        if team_id is None:
            self._pref_status.setText("This project isn't linked to a team yet.")
            self._pref_list.setPlainText("")
            self._pref_save_btn.setEnabled(False)
            return
        self._pref_status.setText("")
        by_kind = {p.event_kind: p for p in prefs}
        lines = []
        for event_kind in KNOWN_EVENT_KINDS:
            pref = by_kind.get(event_kind)
            state = "enabled" if (pref is None or pref.enabled) else "disabled"
            delivery = pref.delivery if pref is not None else "realtime"
            suffix = "" if pref is not None else " (default)"
            lines.append(f"{event_kind}: {state}, {delivery}{suffix}")
        self._pref_list.setPlainText("\n".join(lines))

    def _on_preferences_load_failed(self, message: str) -> None:
        self._pref_status.setText(message)

    def _on_save_preference(self) -> None:
        if self._pref_team_id is None:
            return
        event_kind = self._pref_event_box.currentText()
        enabled = bool(self._pref_enabled_box.currentData())
        delivery = self._pref_delivery_box.currentText()
        team_id = self._pref_team_id
        self._pref_save_btn.setEnabled(False)

        worker = _RoutingMutateWorker(
            lambda: self._services.teams.set_notification_preference(
                team_id, event_kind, enabled, delivery
            )
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self.refresh)
        worker.failed.connect(self._on_preferences_load_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_trigger_rules_loaded(self, team_id: str | None, rules) -> None:
        self._trigger_rules_team_id = team_id
        if team_id is None:
            self._trigger_rules_status.setText(
                "This project isn't linked to a team yet -- link it on the Projects screen."
            )
            self._trigger_rules_list.setPlainText("")
            self._trigger_add_btn.setEnabled(False)
            return
        self._trigger_rules_status.setText("")
        if not rules:
            self._trigger_rules_list.setPlainText(
                "No rules yet -- every event kind queues a changelog note by default."
            )
            return
        lines = [
            f"{r.event_kind}: {r.action} at {r.min_severity}+"
            f"{'' if r.enabled else ' (disabled)'}"
            for r in sorted(rules, key=lambda r: r.event_kind)
        ]
        self._trigger_rules_list.setPlainText("\n".join(lines))

    def _on_trigger_rules_load_failed(self, message: str) -> None:
        self._trigger_rules_status.setText(message)

    def _on_add_trigger_rule(self) -> None:
        if self._trigger_rules_team_id is None:
            return
        event_kind = self._trigger_event_box.currentText()
        min_severity = self._trigger_severity_box.currentText()
        action = self._trigger_action_box.currentText()
        team_id = self._trigger_rules_team_id
        self._trigger_add_btn.setEnabled(False)

        worker = _RoutingMutateWorker(
            lambda: self._services.teams.add_trigger_rule(
                team_id, event_kind, min_severity, action
            )
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self.refresh)
        worker.failed.connect(self._on_trigger_rules_load_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_test(self) -> None:
        self._test_btn.setEnabled(False)
        provider_key = self._provider_box.currentText()
        try:
            provider = build_provider(provider_key)
            self._test_result.setText(f"Contacting {provider.display_name()}…")
            if not provider.is_available():
                self._test_result.setText(self._not_configured_message(provider_key))
                return
            response = provider.generate(
                "Reply with one short, friendly sentence confirming the connection works."
            )
            self._services.usage.record_prompt(response.provider, kind="test")
            self._test_result.setText(f"Success — {provider.display_name()} said:\n{response.text}")
            self.settings_changed.emit()
        except Exception as exc:
            self._test_result.setText(f"Test failed: {exc}")
        finally:
            self._test_btn.setEnabled(True)

    @staticmethod
    def _not_configured_message(provider_key: str) -> str:
        env_var = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}.get(provider_key)
        if env_var:
            return (
                f"{provider_key.capitalize()} isn't configured yet. Set {env_var} in your "
                "environment or a local .env file (see .env.example), then try again. "
                "You can also switch to the mock provider for free offline testing."
            )
        return "This provider is ready to use."
