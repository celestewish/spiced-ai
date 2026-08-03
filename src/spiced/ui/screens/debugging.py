"""Debugging Buddy: crash analysis, outdated-API checks, and code health.

Parsing/scanning happens locally and instantly; every provider call runs on a
worker thread so the window stays responsive. Only a trimmed excerpt is ever
sent — never a full log/script or any project files.
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
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.code_health import MAX_EXCERPT_CHARS as CODE_HEALTH_MAX_EXCERPT_CHARS
from spiced.core.code_health import CodeHealthReview
from spiced.core.code_health import ProviderNotReadyError as CodeHealthNotReadyError
from spiced.core.debugging import (
    SOURCE_FILE,
    SOURCE_PASTE,
    DebugAnalysis,
    ProviderNotReadyError,
)
from spiced.core.version_check import ProviderNotReadyError as VersionCheckNotReadyError
from spiced.core.version_check import VersionCheckReview
from spiced.ui.widgets.source_link import SourceLinkExpander


class _CrashWorker(QObject):
    done = Signal(object)  # DebugAnalysis
    failed = Signal(str)

    def __init__(
        self, services: Services, log_text: str, source_type: str, source_filename: str | None
    ) -> None:
        super().__init__()
        self._services = services
        self._log_text = log_text
        self._source_type = source_type
        self._source_filename = source_filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            project = self._services.active_project()
            team_mode = self._services.team_mode_enabled()
            analysis = self._services.debugging.analyze(
                provider,
                self._log_text,
                project=project,
                source_type=self._source_type,
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
                team_mode=team_mode,
                team_members=self._services.team_prompt_context(project) if team_mode else None,
            )
            # Opt-In Only Telemetry (Phase C): a bare, anonymous event name —
            # no log content, file paths, or project data. No-op unless the
            # developer has explicitly turned this on in Settings.
            self._services.record_telemetry_event("debugging.crash_diagnosis_run")
            self.done.emit(analysis)
        except ProviderNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during analysis: {exc}")


class _VersionCheckWorker(QObject):
    done = Signal(object)  # VersionCheckReview
    failed = Signal(str)

    def __init__(self, services: Services, code_text: str, filename: str | None) -> None:
        super().__init__()
        self._services = services
        self._code_text = code_text
        self._filename = filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.version_check.analyze(
                provider,
                self._code_text,
                project=self._services.active_project(),
                source_filename=self._filename,
                record_usage=self._services.usage.record_prompt,
            )
            self.done.emit(review)
        except VersionCheckNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Something went wrong during the review: {exc}")


class _CodeHealthWorker(QObject):
    done = Signal(object)  # CodeHealthReview
    failed = Signal(str)

    def __init__(self, services: Services, code_text: str, filename: str | None) -> None:
        super().__init__()
        self._services = services
        self._code_text = code_text
        self._filename = filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.code_health.analyze(
                provider,
                self._code_text,
                project=self._services.active_project(),
                source_filename=self._filename,
                record_usage=self._services.usage.record_prompt,
            )
            self._services.record_telemetry_event("debugging.code_health_check_run")
            self.done.emit(review)
        except CodeHealthNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Something went wrong during the review: {exc}")


class DebuggingScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._pending_filename: str | None = None
        self._version_pending_filename: str | None = None
        self._health_pending_filename: str | None = None

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

        title = QLabel("Debugging Buddy")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        self._build_crash_analysis(layout)
        self._build_version_check(layout)
        self._build_code_health(layout)

        self.refresh()

    # --- Explain This Crash -------------------------------------------------

    def _build_crash_analysis(self, layout: QVBoxLayout) -> None:
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
        self._log_input.setFixedHeight(140)
        layout.addWidget(self._log_input)

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
        self._result.setFixedHeight(220)
        layout.addWidget(self._result)

        # Transparent AI Reasoning (Phase C): "why am I seeing this?" for the
        # crash diagnosis — the matched known issue's note, or the log
        # excerpt that was actually sent, whichever applies.
        self._source_link = SourceLinkExpander()
        layout.addWidget(self._source_link)

        history_title = QLabel("Recent sessions")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)

        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setFixedHeight(110)
        layout.addWidget(self._history)

    # --- Version-Aware Suggestions ------------------------------------------

    def _build_version_check(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Outdated-API check (Version-Aware Suggestions)")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Paste a C# script or import a file. Scan checks it against a curated list of "
            "known-deprecated Unity APIs — fully offline, free. Analyze adds an AI narrative "
            "and one-line rationale per hit."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._version_input = QPlainTextEdit()
        self._version_input.setPlaceholderText("Paste a C# script here…")
        self._version_input.setFixedHeight(120)
        layout.addWidget(self._version_input)

        row = QHBoxLayout()
        self._version_import_btn = QPushButton("Import script…")
        self._version_import_btn.clicked.connect(self._on_version_import)
        row.addWidget(self._version_import_btn)
        self._version_scan_btn = QPushButton("Scan (local, free)")
        self._version_scan_btn.clicked.connect(self._on_version_scan)
        row.addWidget(self._version_scan_btn)
        row.addStretch(1)
        self._version_analyze_btn = QPushButton("Analyze with AI")
        self._version_analyze_btn.clicked.connect(self._on_version_analyze)
        row.addWidget(self._version_analyze_btn)
        layout.addLayout(row)

        self._version_result = QTextEdit()
        self._version_result.setReadOnly(True)
        self._version_result.setPlaceholderText("Scan results and AI review will appear here.")
        self._version_result.setFixedHeight(160)
        layout.addWidget(self._version_result)

        self._version_source_link = SourceLinkExpander()
        layout.addWidget(self._version_source_link)

        history_title = QLabel("Recent outdated-API checks")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._version_history = QTextEdit()
        self._version_history.setReadOnly(True)
        self._version_history.setFixedHeight(90)
        layout.addWidget(self._version_history)

    # --- Code Health Dashboard (collapsible) --------------------------------

    def _build_code_health(self, layout: QVBoxLayout) -> None:
        self._health_toggle = QPushButton("▸ Code Health summary (click to expand)")
        self._health_toggle.setObjectName("Ghost")
        self._health_toggle.clicked.connect(self._on_toggle_health)
        layout.addWidget(self._health_toggle)

        self._health_body = QWidget()
        body = QVBoxLayout(self._health_body)
        body.setContentsMargins(0, 6, 0, 0)
        body.setSpacing(8)

        intro = QLabel(
            "A non-judgmental, local read on one pasted file: function length, rough branching "
            "complexity, duplicate blocks, and TODOs. Framed as prioritized suggestions, never "
            "a score that shames you — and it only reflects this one file, not the whole project."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        body.addWidget(intro)

        self._health_input = QPlainTextEdit()
        self._health_input.setPlaceholderText("Paste a script to check its code health…")
        self._health_input.setFixedHeight(120)
        body.addWidget(self._health_input)

        row = QHBoxLayout()
        self._health_import_btn = QPushButton("Import script…")
        self._health_import_btn.clicked.connect(self._on_health_import)
        row.addWidget(self._health_import_btn)
        row.addStretch(1)
        self._health_analyze_btn = QPushButton("Check code health")
        self._health_analyze_btn.clicked.connect(self._on_health_analyze)
        row.addWidget(self._health_analyze_btn)
        body.addLayout(row)

        self._health_result = QTextEdit()
        self._health_result.setReadOnly(True)
        self._health_result.setPlaceholderText("Your code-health summary will appear here.")
        self._health_result.setFixedHeight(160)
        body.addWidget(self._health_result)

        self._health_source_link = SourceLinkExpander()
        body.addWidget(self._health_source_link)

        history_title = QLabel("Recent code-health checks")
        history_title.setObjectName("SectionTitle")
        body.addWidget(history_title)
        self._health_history = QTextEdit()
        self._health_history.setReadOnly(True)
        self._health_history.setFixedHeight(90)
        body.addWidget(self._health_history)

        self._health_body.setVisible(False)
        layout.addWidget(self._health_body)

    def _on_toggle_health(self) -> None:
        expanded = not self._health_body.isVisible()
        self._health_body.setVisible(expanded)
        arrow = "▾" if expanded else "▸"
        action = "collapse" if expanded else "expand"
        self._health_toggle.setText(f"{arrow} Code Health summary (click to {action})")

    # --- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
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
        self._refresh_version_history()
        self._refresh_health_history()

    def _refresh_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._history.setPlainText("Sessions are saved once you select an active project.")
            return
        sessions = self._services.debugging.history(project.id, limit=10)
        if not sessions:
            self._history.setPlainText("No debugging sessions saved for this project yet.")
            return
        lines = []
        for s in sessions:
            error = s.detected_error_type or "Unknown error"
            where = f" in {s.detected_file}" if s.detected_file else ""
            summary = s.summary or ""
            lines.append(f"[{s.created_at}] {error}{where}\n    {summary}")
        self._history.setPlainText("\n".join(lines))

    def _refresh_version_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._version_history.setPlainText(
                "Checks are saved once you select an active project."
            )
            return
        reports = self._services.version_check.history(project.id, limit=10)
        if not reports:
            self._version_history.setPlainText(
                "No outdated-API checks saved for this project yet."
            )
            return
        lines = [
            f"[{r.created_at}] {len(r.hits)} hit(s)\n    {r.ai_summary or ''}" for r in reports
        ]
        self._version_history.setPlainText("\n".join(lines))

    def _refresh_health_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._health_history.setPlainText("Checks are saved once you select an active project.")
            return
        reports = self._services.code_health.history(project.id, limit=10)
        if not reports:
            self._health_history.setPlainText("No code-health checks saved for this project yet.")
            return
        lines = [f"[{r.created_at}]\n    {r.ai_summary or ''}" for r in reports]
        self._health_history.setPlainText("\n".join(lines))

    # --- Crash analysis handlers ---------------------------------------------

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
        self._worker = _CrashWorker(self._services, log_text, source_type, filename)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, analysis: DebugAnalysis) -> None:
        text = analysis.response_text
        if analysis.regression_match is not None:
            text = text + "\n\nKnown-issue match:\n- " + analysis.regression_match.note
        self._result.setPlainText(text)
        if analysis.regression_match is not None:
            description = analysis.regression_match.note
        elif analysis.session is not None and analysis.session.source_filename:
            description = f"From the imported log file \"{analysis.session.source_filename}\"."
        else:
            description = "From the pasted crash log excerpt below."
        self._source_link.set_source(description, analysis.parsed.excerpt)
        self._pending_filename = None
        self._set_busy(False)
        self.usage_changed.emit()
        self._refresh_history()

    def _on_failed(self, message: str) -> None:
        self._result.setPlainText(message)
        self._source_link.set_source(None, None)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._analyze_btn.setEnabled(not busy)
        self._analyze_btn.setText("Analyzing…" if busy else "Analyze")

    # --- Version-check handlers -----------------------------------------------

    def _on_version_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a script", "", "C# files (*.cs);;All files (*)"
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
        self._version_input.setPlainText(text)
        self._version_pending_filename = Path(path).name

    def _on_version_scan(self) -> None:
        code_text = self._version_input.toPlainText().strip()
        if not code_text:
            QMessageBox.information(
                self, "Nothing to scan", "Paste a script or import a file first."
            )
            return
        parsed = self._services.version_check.scan(code_text)
        if not parsed.hits:
            self._version_result.setPlainText(
                "Local scan (no AI used): none of Spiced's known-deprecated APIs were found.\n\n"
                "Click Analyze with AI for a written review, or keep this scan for free."
            )
            return
        lines = ["Local scan (no AI used):"]
        for hit in parsed.hits:
            lines.append(
                f"- Line {hit.line_number}: {hit.api_name} -> {hit.replacement} "
                f"(deprecated in {hit.deprecated_in})\n    {hit.reason}"
            )
        lines.append("\nClick Analyze with AI for a written review.")
        self._version_result.setPlainText("\n".join(lines))

    def _on_version_analyze(self) -> None:
        code_text = self._version_input.toPlainText().strip()
        if not code_text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste a script or import a file first."
            )
            return
        filename = self._version_pending_filename
        self._version_analyze_btn.setEnabled(False)
        self._version_analyze_btn.setText("Analyzing…")
        self._version_result.setPlainText("Reading the script and thinking it through…")

        self._thread = QThread()
        self._worker = _VersionCheckWorker(self._services, code_text, filename)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_version_done)
        self._worker.failed.connect(self._on_version_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_version_done(self, review: VersionCheckReview) -> None:
        self._version_result.setPlainText(review.response_text)
        hit_count = len(review.parsed.hits)
        description = (
            f"From {hit_count} deprecated-API hit(s) found by the local scan of the "
            "pasted/imported script below."
        )
        self._version_source_link.set_source(description, review.parsed.excerpt)
        self._version_pending_filename = None
        self._version_analyze_btn.setEnabled(True)
        self._version_analyze_btn.setText("Analyze with AI")
        self.usage_changed.emit()
        self._refresh_version_history()

    def _on_version_failed(self, message: str) -> None:
        self._version_result.setPlainText(message)
        self._version_source_link.set_source(None, None)
        self._version_analyze_btn.setEnabled(True)
        self._version_analyze_btn.setText("Analyze with AI")

    # --- Code health handlers --------------------------------------------------

    def _on_health_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a script", "", "C# files (*.cs);;All files (*)"
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
        self._health_input.setPlainText(text)
        self._health_pending_filename = Path(path).name

    def _on_health_analyze(self) -> None:
        code_text = self._health_input.toPlainText().strip()
        if not code_text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste a script or import a file first."
            )
            return
        filename = self._health_pending_filename
        self._health_analyze_btn.setEnabled(False)
        self._health_analyze_btn.setText("Checking…")
        self._health_result.setPlainText("Reading the file and thinking it through…")

        self._thread = QThread()
        self._worker = _CodeHealthWorker(self._services, code_text, filename)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_health_done)
        self._worker.failed.connect(self._on_health_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_health_done(self, review: CodeHealthReview) -> None:
        self._health_result.setPlainText(review.response_text)
        excerpt = (
            review.report.raw_excerpt
            if review.report is not None
            else self._health_input.toPlainText().strip()[:CODE_HEALTH_MAX_EXCERPT_CHARS]
        )
        self._health_source_link.set_source(
            "From the pasted/imported script below (this excerpt, plus the local metrics "
            "shown above, is what was sent to the AI).",
            excerpt,
        )
        self._health_pending_filename = None
        self._health_analyze_btn.setEnabled(True)
        self._health_analyze_btn.setText("Check code health")
        self.usage_changed.emit()
        self._refresh_health_history()

    def _on_health_failed(self, message: str) -> None:
        self._health_result.setPlainText(message)
        self._health_source_link.set_source(None, None)
        self._health_analyze_btn.setEnabled(True)
        self._health_analyze_btn.setText("Check code health")
