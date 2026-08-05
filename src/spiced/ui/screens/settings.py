"""Settings: AI provider, mock plan, Team Mode toggle, and a connection test."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spiced.ai import available_providers, build_provider
from spiced.app.services import Services
from spiced.core.plans import PLANS
from spiced.ui.auth_dialog import AuthDialog


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
