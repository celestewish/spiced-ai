"""Feedback Review: parse player feedback locally, then review it with AI.

Local parsing and heuristic classification work fully offline with no AI
provider — the developer can always preview what Spiced detected before spending
a prompt. The AI review runs the selected provider on a worker thread; only a
trimmed excerpt and local counts are ever sent — never project files.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.feedback import SOURCE_FILE, SOURCE_PASTE, FeedbackReview, ProviderNotReadyError


class _Worker(QObject):
    done = Signal(object)  # FeedbackReview
    failed = Signal(str)

    def __init__(
        self,
        services: Services,
        feedback_text: str,
        source_type: str,
        source_label: str | None,
        source_filename: str | None,
    ) -> None:
        super().__init__()
        self._services = services
        self._feedback_text = feedback_text
        self._source_type = source_type
        self._source_label = source_label
        self._source_filename = source_filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.feedback.analyze(
                provider,
                self._feedback_text,
                project=self._services.active_project(),
                source_type=self._source_type,
                source_label=self._source_label,
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
            )
            self.done.emit(review)
        except ProviderNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during analysis: {exc}")


class FeedbackScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._pending_filename: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("Feedback Review")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        self._build_input(layout)
        self._build_result(layout)
        self._build_history(layout)

        self.refresh()

    # --- Input -------------------------------------------------------------

    def _build_input(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Add feedback")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Paste playtester comments or import a .txt/.md/.csv/.json file. Spiced parses it "
            "locally, groups it into themes, and separates bugs from design preferences — it "
            "never scrapes anything and never decides your design for you."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        label_row = QHBoxLayout()
        label_row.addWidget(QLabel("Source label (optional):"))
        self._label_input = QLineEdit()
        self._label_input.setPlaceholderText("e.g. Playtest 1, Discord, Survey, itch.io comments")
        label_row.addWidget(self._label_input, 1)
        layout.addLayout(label_row)

        self._feedback_input = QPlainTextEdit()
        self._feedback_input.setPlaceholderText("Paste player feedback here…")
        self._feedback_input.setFixedHeight(150)
        layout.addWidget(self._feedback_input)

        row = QHBoxLayout()
        self._import_btn = QPushButton("Import feedback file…")
        self._import_btn.clicked.connect(self._on_import)
        row.addWidget(self._import_btn)
        self._preview_btn = QPushButton("Preview (local only)")
        self._preview_btn.clicked.connect(self._on_preview)
        row.addWidget(self._preview_btn)
        row.addStretch(1)
        self._analyze_btn = QPushButton("Analyze")
        self._analyze_btn.clicked.connect(self._on_analyze)
        row.addWidget(self._analyze_btn)
        layout.addLayout(row)

    def _build_result(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Review")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        self._result = QTextEdit()
        self._result.setReadOnly(True)
        self._result.setPlaceholderText(
            "Your structured feedback review will appear here. Use Preview to see the local "
            "parse and category counts without an AI provider."
        )
        self._result.setFixedHeight(240)
        layout.addWidget(self._result)

    def _build_history(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Recent feedback batches")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setFixedHeight(120)
        layout.addWidget(self._history)

    # --- Refresh & state ---------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        has_project = project is not None
        if not has_project:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to "
                "analyze and save feedback. You can still Preview a local parse below."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")
        self._analyze_btn.setEnabled(has_project)
        self._refresh_history()

    def _refresh_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._history.setPlainText("Feedback batches are saved once you select a project.")
            return
        batches = self._services.feedback.history(project.id, limit=10)
        if not batches:
            self._history.setPlainText(
                "No feedback batches saved yet. Paste playtester comments above, Preview the "
                "local parse, then Analyze to group them into themes and separate bugs from "
                "design preferences. (Load the demo from Help to see an example.)"
            )
            return
        lines = []
        for batch in batches:
            name = batch.source_label or batch.source_filename or "feedback"
            themes = ", ".join(batch.themes[:3]) if batch.themes else "—"
            summary = batch.ai_summary or ""
            lines.append(
                f"[{batch.created_at}] {name} · {batch.entry_count} entries\n"
                f"    themes: {themes}\n    {summary}"
            )
        self._history.setPlainText("\n".join(lines))

    # --- Handlers ----------------------------------------------------------

    def _current_text(self) -> str:
        return self._feedback_input.toPlainText().strip()

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import feedback",
            "",
            "Feedback files (*.txt *.md *.csv *.json);;All files (*)",
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
        self._feedback_input.setPlainText(text)
        self._pending_filename = Path(path).name
        self._on_preview()

    def _on_preview(self) -> None:
        text = self._current_text()
        if not text:
            QMessageBox.information(
                self, "Nothing to preview", "Paste feedback or import a file first."
            )
            return
        preview = self._services.feedback.preview(text, filename=self._pending_filename)
        parsed = preview.parsed
        lines = [
            "Local parse (no AI used):",
            f"- Format: {parsed.source_format}",
            f"- Entries detected: {parsed.entry_count}",
            f"- Parser confidence: {parsed.confidence}",
        ]
        if self._pending_filename:
            lines.append(f"- File: {self._pending_filename}")
        if parsed.detected_fields:
            lines.append(f"- Detected fields: {', '.join(parsed.detected_fields)}")
        if preview.classification.counts:
            lines.append("- Local categories (heuristic):")
            for category, count in sorted(
                preview.classification.counts.items(), key=lambda kv: kv[1], reverse=True
            ):
                lines.append(f"    • {category}: {count}")
        lines.append("\nClick Analyze for the full AI review.")
        self._result.setPlainText("\n".join(lines))

    def _on_analyze(self) -> None:
        text = self._current_text()
        if not text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste feedback or import a file first."
            )
            return
        source_type = SOURCE_FILE if self._pending_filename else SOURCE_PASTE
        label = self._label_input.text().strip() or None
        self._set_busy(True)
        self._result.setPlainText("Reading the feedback and thinking it through…")

        self._thread = QThread()
        self._worker = _Worker(
            self._services, text, source_type, label, self._pending_filename
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, review: FeedbackReview) -> None:
        self._result.setPlainText(review.response_text)
        self._pending_filename = None
        self._set_busy(False)
        self.usage_changed.emit()
        self._refresh_history()

    def _on_failed(self, message: str) -> None:
        self._result.setPlainText(message)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._analyze_btn.setEnabled(not busy and self._services.active_project() is not None)
        self._analyze_btn.setText("Analyzing…" if busy else "Analyze")
