"""Settings: AI provider, mock plan, Team Mode toggle, and a connection test."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.ai import available_providers, build_provider
from spiced.app.services import Services
from spiced.core.notification_routing import (
    DEFAULT_EVENT_KIND_DISCIPLINES,
    KNOWN_EVENT_KINDS,
    disciplines_for_event,
)
from spiced.core.plans import PLANS
from spiced.ui.auth_dialog import AuthDialog
from spiced.ui.screens.team import SUGGESTED_DISCIPLINES
from spiced.ui.thread_utils import launch_worker


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


class SettingsScreen(QWidget):
    settings_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)

        # AI provider (OpenAI is the default; mock is free/offline; Gemini optional)
        self._provider_box = QComboBox()
        self._provider_box.addItems(available_providers())
        self._provider_box.setCurrentText(self._services.provider_name())
        self._provider_box.currentTextChanged.connect(self._on_provider_changed)
        form.addRow("AI provider", self._provider_box)

        # Mock plan
        self._plan_box = QComboBox()
        for plan in PLANS.values():
            self._plan_box.addItem(plan.label, plan.key)
        current_key = self._services.usage.current_plan().key
        idx = self._plan_box.findData(current_key)
        if idx >= 0:
            self._plan_box.setCurrentIndex(idx)
        self._plan_box.currentIndexChanged.connect(self._on_plan_changed)
        form.addRow("Plan (mock)", self._plan_box)

        layout.addLayout(form)

        note = QLabel(
            "Plans are a preview of a future offering. Spiced does not process payments "
            "or create accounts, and no usage information leaves your machine."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        # Solo-Dev Mode vs. Small-Team Mode (off/solo by default)
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

        self._build_notification_routing_section(layout)
        self._build_notification_preferences_section(layout)

        # Connection test for the selected provider
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
        self._test_btn = QPushButton("Send test prompt")
        self._test_btn.setObjectName("Ghost")
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

    # --- Relevance-Based Notifications: routing config (Phase J, #6) --------
    #
    # Scope boundary: this only edits the ROUTING rules (which discipline(s)
    # an event kind routes to) plus shows the default mapping. The actual
    # inbox (bell icon + dropdown) is the Notification Center's UI (Phase K,
    # section 9 part 1) in the top bar -- see ui.top_bar.TopBar and
    # ui.notification_center. Only usable for a team-linked active project,
    # since routing rules are saved per-team.

    def _build_notification_routing_section(self, layout: QVBoxLayout) -> None:
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
        self._routing_event_box = QComboBox()
        self._routing_event_box.addItems(KNOWN_EVENT_KINDS)
        row.addWidget(self._routing_event_box, 1)
        self._routing_discipline_box = QComboBox()
        self._routing_discipline_box.setEditable(True)
        self._routing_discipline_box.addItems(SUGGESTED_DISCIPLINES)
        row.addWidget(self._routing_discipline_box, 1)
        self._routing_add_btn = QPushButton("Add rule")
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
        self._pref_event_box = QComboBox()
        self._pref_event_box.addItems(KNOWN_EVENT_KINDS)
        row.addWidget(self._pref_event_box, 1)
        self._pref_enabled_box = QComboBox()
        self._pref_enabled_box.addItem("Enabled", True)
        self._pref_enabled_box.addItem("Disabled", False)
        row.addWidget(self._pref_enabled_box, 1)
        self._pref_delivery_box = QComboBox()
        self._pref_delivery_box.addItems(["realtime", "hourly", "daily"])
        row.addWidget(self._pref_delivery_box, 1)
        self._pref_save_btn = QPushButton("Save preference")
        self._pref_save_btn.clicked.connect(self._on_save_preference)
        row.addWidget(self._pref_save_btn)
        layout.addLayout(row)

    def refresh(self) -> None:
        """Reload the notification routing + preferences panels for the
        active project's team, if any. Safe to call whenever the active
        project changes."""
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
