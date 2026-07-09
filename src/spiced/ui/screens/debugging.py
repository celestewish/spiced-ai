"""Debugging Buddy: paste or import a Unity log and get calm, structured help.

Parsing happens locally and instantly; the provider call runs on a worker
thread so the window stays responsive. Only a trimmed excerpt is ever sent —
never the full log or any project files.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.debugging import (
    SOURCE_FILE,
    SOURCE_PASTE,
    DebugAnalysis,
    ProviderNotReadyError,
)


class _Worker(QObject):
    done = Signal(object)  # DebugAnalysis
    failed = Signal(str)

    def __init__(
        self,
        services: Services,
        log_text: str,
        source_type: str,
        source_filename: str | None,
    ) -> None:
        super().__init__()
        self._services = services
        self._log_text = log_text
        self._source_type = source_type
        self._source_filename = source_filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            analysis = self._services.debugging.analyze(
                provider,
                self._log_text,
                project=self._services.active_project(),
                source_type=self._source_type,
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
            )
            self.done.emit(analysis)
        except ProviderNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during analysis: {exc}")


class DebuggingScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._pending_filename: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("Debugging Buddy")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        intro = QLabel(
            "Paste a Unity error log or import a .log/.txt file. I'll read it locally, point "
            "at the likely cause, and suggest safe next steps — you stay in control."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._log_input = QPlainTextEdit()
        self._log_input.setPlaceholderText(
            "Paste your Unity console output or Editor.log excerpt here…"
        )
        layout.addWidget(self._log_input, 1)

        row = QHBoxLayout()
        self._import_btn = QPushButton("Import log file…")
        self._import_btn.clicked.connect(self._import_file)
        row.addWidget(self._import_btn)
        row.addStretch(1)
        self._analyze_btn = QPushButton("Analyze")
        self._analyze_btn.clicked.connect(self._on_analyze)
        row.addWidget(self._analyze_btn)
        layout.addLayout(row)

        result_title = QLabel("Analysis")
        result_title.setObjectName("SectionTitle")
        layout.addWidget(result_title)

        self._result = QTextEdit()
        self._result.setReadOnly(True)
        self._result.setPlaceholderText("Your structured debugging guidance will appear here.")
        layout.addWidget(self._result, 1)

        history_title = QLabel("Recent sessions")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)

        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setFixedHeight(120)
        layout.addWidget(self._history)

        self.refresh()

    def refresh(self) -> None:
        """Refresh the active-project banner and the history list."""
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project yet. You can still analyze a log, but pick a project on "
                "the Projects screen to save sessions and add Unity context."
            )
        else:
            if project.is_valid_unity:
                status = "valid Unity project"
            elif project.path:
                status = "folder not recognized as Unity"
            else:
                status = "no Unity folder connected"
            self._context_label.setText(f"Active project: {project.name} · {status}")
        self._refresh_history()

    def _refresh_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._history.setPlainText("Sessions are saved once you select an active project.")
            return
        sessions = self._services.debugging.history(project.id, limit=10)
        if not sessions:
            self._history.setPlainText(
                "No debugging sessions saved yet. Paste a Unity error above and click Analyze — "
                "each one is saved here so you can revisit the likely cause and next steps. "
                "(Load the demo from Help to see an example.)"
            )
            return
        lines = []
        for s in sessions:
            error = s.detected_error_type or "Unknown error"
            where = f" in {s.detected_file}" if s.detected_file else ""
            summary = s.summary or ""
            lines.append(f"[{s.created_at}] {error}{where}\n    {summary}")
        self._history.setPlainText("\n".join(lines))

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a Unity log", "", "Log files (*.log *.txt);;All files (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.warning(
                self, "Could not read file", f"Sorry, I couldn't open that file:\n{exc}"
            )
            return
        self._log_input.setPlainText(text)
        self._pending_filename = Path(path).name

    def _on_analyze(self) -> None:
        log_text = self._log_input.toPlainText().strip()
        if not log_text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste a log or import a file first."
            )
            return

        source_type = SOURCE_FILE if self._pending_filename else SOURCE_PASTE
        filename = self._pending_filename
        self._set_busy(True)
        self._result.setPlainText("Reading the log and thinking it through…")

        self._thread = QThread()
        self._worker = _Worker(self._services, log_text, source_type, filename)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, analysis: DebugAnalysis) -> None:
        self._result.setPlainText(analysis.response_text)
        self._pending_filename = None
        self._set_busy(False)
        self.usage_changed.emit()
        self._refresh_history()

    def _on_failed(self, message: str) -> None:
        self._result.setPlainText(message)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._analyze_btn.setEnabled(not busy)
        self._analyze_btn.setText("Analyzing…" if busy else "Analyze")
