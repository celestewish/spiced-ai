"""Settings: AI provider, mock plan, and a real connection test prompt."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spiced.ai import available_providers, build_provider
from spiced.app.services import Services
from spiced.core.plans import PLANS


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

        intro = QLabel(
            "Choose which AI provider Spiced uses and confirm it's set up. The mock provider "
            "works offline with no key, so you can try every screen for free before adding one. "
            "Nothing here leaves your machine except the short connection test you trigger."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

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
