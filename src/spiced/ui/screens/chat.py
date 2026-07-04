"""Debugging Buddy: a calm chat workspace backed by the active AI provider.

The provider runs on a worker thread so the window stays responsive. Only the
text the developer types is sent; project files are never included in Phase 0.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services


class _Worker(QObject):
    done = Signal(str, str)  # (text, provider_name)
    failed = Signal(str)

    def __init__(self, services: Services, prompt: str) -> None:
        super().__init__()
        self._services = services
        self._prompt = prompt

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            if not provider.is_available():
                self.failed.emit(
                    f"The {provider.display_name()} provider isn't ready. "
                    "Check Settings and your GEMINI_API_KEY, or switch to the mock provider."
                )
                return
            response = provider.generate(self._prompt)
            self._services.usage.record_prompt(response.provider)
            self.done.emit(response.text, provider.display_name())
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong reaching the provider: {exc}")


class ChatScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._thread: QThread | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("Debugging Buddy")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        intro = QLabel(
            "Talk through a bug or a tricky bit of behavior. I'll help you reason about "
            "it — you stay in control of any changes."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        layout.addWidget(self._transcript, 1)

        self._input = QPlainTextEdit()
        self._input.setPlaceholderText("Describe what's happening… (Ctrl+Enter to send)")
        self._input.setFixedHeight(90)
        layout.addWidget(self._input)

        row = QHBoxLayout()
        row.addStretch(1)
        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._on_send)
        row.addWidget(self._send_btn)
        layout.addLayout(row)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._on_send()
            return
        super().keyPressEvent(event)

    def _append(self, speaker: str, text: str) -> None:
        self._transcript.append(f"<b>{speaker}:</b> {text}<br>")

    def _on_send(self) -> None:
        prompt = self._input.toPlainText().strip()
        if not prompt:
            return
        self._append("You", prompt)
        self._input.clear()
        self._set_busy(True)

        self._thread = QThread()
        self._worker = _Worker(self._services, prompt)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, text: str, provider_name: str) -> None:
        self._append(f"Spiced · {provider_name}", text.replace("\n", "<br>"))
        self._set_busy(False)
        self.usage_changed.emit()

    def _on_failed(self, message: str) -> None:
        self._append("Spiced", message)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._send_btn.setEnabled(not busy)
        self._send_btn.setText("Thinking…" if busy else "Send")
