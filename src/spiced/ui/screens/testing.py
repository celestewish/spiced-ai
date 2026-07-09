"""Automated Testing: author manual test cases and review imported results.

Manual test-case creation and status tracking work fully offline with no AI
provider. Result analysis runs the selected provider on a worker thread; only a
trimmed excerpt is ever sent — never project files.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.testing import SOURCE_FILE, SOURCE_PASTE, ProviderNotReadyError, TestReview
from spiced.storage.test_cases import CATEGORIES, PRIORITIES, STATUSES

_USER_ROLE = 0x0100


class _Worker(QObject):
    done = Signal(object)  # TestReview
    failed = Signal(str)

    def __init__(
        self, services: Services, results_text: str, source_type: str, source_filename: str | None
    ) -> None:
        super().__init__()
        self._services = services
        self._results_text = results_text
        self._source_type = source_type
        self._source_filename = source_filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.testing.analyze(
                provider,
                self._results_text,
                project=self._services.active_project(),
                source_type=self._source_type,
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
            )
            self.done.emit(review)
        except ProviderNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during analysis: {exc}")


class TestingScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._pending_filename: str | None = None
        self._selected_case_id: int | None = None

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

        title = QLabel("Automated Testing")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        self._build_case_form(layout)
        self._build_case_list(layout)
        self._build_analyze(layout)

        self.refresh()

    # --- Test case creation ------------------------------------------------

    def _build_case_form(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Add a test case")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        form = QFormLayout()
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("e.g. Player takes damage from spikes")
        self._category_input = QComboBox()
        self._category_input.addItems(CATEGORIES)
        self._category_input.setCurrentText("General")
        self._priority_input = QComboBox()
        self._priority_input.addItems(PRIORITIES)
        self._priority_input.setCurrentText("Medium")
        self._steps_input = QPlainTextEdit()
        self._steps_input.setPlaceholderText("Steps to reproduce / perform the check…")
        self._steps_input.setFixedHeight(60)
        self._expected_input = QPlainTextEdit()
        self._expected_input.setPlaceholderText("What should happen…")
        self._expected_input.setFixedHeight(60)

        form.addRow("Title", self._title_input)
        form.addRow("Category", self._category_input)
        form.addRow("Priority", self._priority_input)
        form.addRow("Steps", self._steps_input)
        form.addRow("Expected", self._expected_input)
        layout.addLayout(form)

        row = QHBoxLayout()
        self._selection_hint = QLabel("Editing a new test case.")
        self._selection_hint.setObjectName("Muted")
        row.addWidget(self._selection_hint)
        row.addStretch(1)
        self._clear_btn = QPushButton("New / clear")
        self._clear_btn.clicked.connect(self._on_clear_selection)
        row.addWidget(self._clear_btn)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._on_delete_case)
        row.addWidget(self._delete_btn)
        self._add_btn = QPushButton("Add test case")
        self._add_btn.clicked.connect(self._on_add_case)
        row.addWidget(self._add_btn)
        self._save_btn = QPushButton("Save changes")
        self._save_btn.clicked.connect(self._on_save_case)
        row.addWidget(self._save_btn)
        layout.addLayout(row)

    def _build_case_list(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Test cases")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        self._case_list = QListWidget()
        self._case_list.setFixedHeight(160)
        self._case_list.currentItemChanged.connect(self._on_case_selected)
        layout.addWidget(self._case_list)

        self._cases_empty = QLabel(
            "No test cases yet. Test cases are a lightweight manual QA checklist — track what "
            "you've verified and what still needs a pass before you share a build. Add one "
            "above, or load the demo from Help to see a set with mixed statuses."
        )
        self._cases_empty.setObjectName("Muted")
        self._cases_empty.setWordWrap(True)
        layout.addWidget(self._cases_empty)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Set status:"))
        self._status_input = QComboBox()
        self._status_input.addItems(STATUSES)
        self._status_input.currentTextChanged.connect(self._on_status_choice_changed)
        status_row.addWidget(self._status_input)
        self._failure_note_input = QLineEdit()
        self._failure_note_input.setPlaceholderText("Failure note (used when status is Fail)")
        status_row.addWidget(self._failure_note_input, 1)
        self._update_status_btn = QPushButton("Update")
        self._update_status_btn.clicked.connect(self._on_update_status)
        status_row.addWidget(self._update_status_btn)
        layout.addLayout(status_row)

    def _build_analyze(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Analyze test results")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Paste test output or import a .txt/.log/.json/.xml file. Spiced reads it locally, "
            "then summarizes pass/fail and suggests a retest checklist — it never ran the tests."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._results_input = QPlainTextEdit()
        self._results_input.setPlaceholderText("Paste your test-run output here…")
        self._results_input.setFixedHeight(120)
        layout.addWidget(self._results_input)

        row = QHBoxLayout()
        self._import_btn = QPushButton("Import result file…")
        self._import_btn.clicked.connect(self._on_import)
        row.addWidget(self._import_btn)
        row.addStretch(1)
        self._analyze_btn = QPushButton("Analyze")
        self._analyze_btn.clicked.connect(self._on_analyze)
        row.addWidget(self._analyze_btn)
        layout.addLayout(row)

        self._result = QTextEdit()
        self._result.setReadOnly(True)
        self._result.setPlaceholderText("Your structured test-result review will appear here.")
        self._result.setFixedHeight(200)
        layout.addWidget(self._result)

        history_title = QLabel("Recent test runs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setFixedHeight(110)
        layout.addWidget(self._history)

    # --- Refresh & state ---------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        has_project = project is not None
        if not has_project:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to "
                "add test cases and save test runs."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")

        for widget in (
            self._add_btn,
            self._title_input,
            self._update_status_btn,
        ):
            widget.setEnabled(has_project)

        self._refresh_cases()
        self._refresh_history()
        self._update_edit_buttons()

    def _update_edit_buttons(self) -> None:
        has_selection = self._selected_case_id is not None
        self._save_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)
        self._clear_btn.setEnabled(has_selection)
        if has_selection:
            self._selection_hint.setText("Editing the selected test case.")
        else:
            self._selection_hint.setText("Editing a new test case.")

    def _refresh_cases(self) -> None:
        self._case_list.blockSignals(True)
        self._case_list.clear()
        project = self._services.active_project()
        cases = self._services.testing.list_cases(project.id) if project else []
        for case in cases:
            note = f"  — {case.failure_note}" if case.status == "Fail" and case.failure_note else ""
            label = f"[{case.status}] {case.title}  ·  {case.category}  ·  {case.priority}{note}"
            item = QListWidgetItem(label)
            item.setData(_USER_ROLE, case.id)
            self._case_list.addItem(item)
        self._case_list.blockSignals(False)
        self._cases_empty.setVisible(not cases)
        self._case_list.setVisible(bool(cases))

    def _refresh_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._history.setPlainText("Test runs are saved once you select an active project.")
            return
        runs = self._services.testing.history(project.id, limit=10)
        if not runs:
            self._history.setPlainText(
                "No test runs saved yet. Paste or import results above and click Analyze to get "
                "a pass/fail summary and a retest checklist — Spiced never runs the tests itself."
            )
            return
        lines = []
        for run in runs:
            s = run.parsed_summary
            counts = f"{s.get('passed', 0)} passed / {s.get('failed', 0)} failed"
            name = f" · {run.source_filename}" if run.source_filename else ""
            summary = run.ai_summary or ""
            lines.append(f"[{run.created_at}]{name} · {counts}\n    {summary}")
        self._history.setPlainText("\n".join(lines))

    # --- Handlers ----------------------------------------------------------

    def _on_add_case(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        title = self._title_input.text().strip()
        if not title:
            QMessageBox.information(self, "Title needed", "Please enter a test case title.")
            return
        self._services.testing.create_case(
            project_id=project.id,
            title=title,
            category=self._category_input.currentText(),
            priority=self._priority_input.currentText(),
            steps=self._steps_input.toPlainText().strip() or None,
            expected_result=self._expected_input.toPlainText().strip() or None,
        )
        self._selected_case_id = None
        self._case_list.setCurrentItem(None)
        self._title_input.clear()
        self._steps_input.clear()
        self._expected_input.clear()
        self._refresh_cases()
        self._update_edit_buttons()

    def _on_case_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            self._selected_case_id = None
            self._update_edit_buttons()
            return
        case_id = current.data(_USER_ROLE)
        if case_id is None:
            return
        case = self._services.testing.get_case(int(case_id))
        self._selected_case_id = case.id
        self._title_input.setText(case.title)
        self._category_input.setCurrentText(case.category)
        self._priority_input.setCurrentText(case.priority)
        self._steps_input.setPlainText(case.steps or "")
        self._expected_input.setPlainText(case.expected_result or "")
        self._status_input.setCurrentText(case.status)
        self._failure_note_input.setText(case.failure_note or "")
        self._on_status_choice_changed(case.status)
        self._update_edit_buttons()

    def _on_clear_selection(self) -> None:
        self._selected_case_id = None
        self._case_list.setCurrentItem(None)
        self._title_input.clear()
        self._category_input.setCurrentText("General")
        self._priority_input.setCurrentText("Medium")
        self._steps_input.clear()
        self._expected_input.clear()
        self._status_input.setCurrentText("Not Run")
        self._failure_note_input.clear()
        self._on_status_choice_changed("Not Run")
        self._update_edit_buttons()

    def _on_save_case(self) -> None:
        if self._selected_case_id is None:
            return
        title = self._title_input.text().strip()
        if not title:
            QMessageBox.information(self, "Title needed", "Please enter a test case title.")
            return
        status = self._status_input.currentText()
        self._services.testing.update_case(
            self._selected_case_id,
            title=title,
            category=self._category_input.currentText(),
            priority=self._priority_input.currentText(),
            steps=self._steps_input.toPlainText().strip() or None,
            expected_result=self._expected_input.toPlainText().strip() or None,
            status=status,
            failure_note=self._failure_note_input.text().strip() or None,
        )
        self._refresh_cases()
        self._update_edit_buttons()

    def _on_delete_case(self) -> None:
        if self._selected_case_id is None:
            return
        confirm = QMessageBox.question(
            self,
            "Delete test case?",
            "Delete this test case? Saved test-run history is not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._services.testing.delete_case(self._selected_case_id)
        self._on_clear_selection()
        self._refresh_cases()

    def _on_status_choice_changed(self, status: str) -> None:
        self._failure_note_input.setEnabled(status == "Fail")

    def _on_update_status(self) -> None:
        item = self._case_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Select a test case", "Pick a test case from the list.")
            return
        case_id = int(item.data(_USER_ROLE))
        status = self._status_input.currentText()
        note = self._failure_note_input.text().strip() or None
        self._services.testing.set_status(case_id, status, note)
        self._refresh_cases()

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import test results",
            "",
            "Result files (*.txt *.log *.json *.xml);;All files (*)",
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
        self._results_input.setPlainText(text)
        self._pending_filename = Path(path).name

    def _on_analyze(self) -> None:
        results_text = self._results_input.toPlainText().strip()
        if not results_text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste test output or import a file first."
            )
            return
        source_type = SOURCE_FILE if self._pending_filename else SOURCE_PASTE
        filename = self._pending_filename
        self._set_busy(True)
        self._result.setPlainText("Reading the results and thinking it through…")

        self._thread = QThread()
        self._worker = _Worker(self._services, results_text, source_type, filename)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, review: TestReview) -> None:
        self._result.setPlainText(review.response_text)
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
