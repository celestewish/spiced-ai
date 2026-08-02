"""Automated Testing: functional test cases, performance, and accessibility.

Three tabs, each following the same pattern: local/deterministic parsing and
(for Functional) manual test-case tracking work fully offline with no AI
provider; the AI review runs the selected provider on a worker thread. Only a
trimmed excerpt is ever sent — never project files. The one exception is the
opt-in "Run Unity tests" section: when a project has explicitly enabled it
(on the Projects screen), Spiced launches that project's own Unity Editor
headlessly to run its tests, then feeds the results through the same local
parser and AI review as a pasted result.
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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.accessibility import AccessibilityReview
from spiced.core.accessibility import ProviderNotReadyError as AccessibilityNotReadyError
from spiced.core.hardware_simulation import available_tiers
from spiced.core.performance import PerformanceReview
from spiced.core.performance import ProviderNotReadyError as PerformanceNotReadyError
from spiced.core.testing import (
    SOURCE_FILE,
    SOURCE_PASTE,
    SOURCE_UNITY_RUN,
    ProviderNotReadyError,
    TestReview,
)
from spiced.core.unity_test_runner import EDIT_MODE, PLAY_MODE, resolve_unity_editor, run_tests
from spiced.storage.known_issues import STATUS_RESOLVED
from spiced.storage.test_cases import CATEGORIES, PRIORITIES, STATUSES

_USER_ROLE = 0x0100
_NO_HARDWARE = "(none — no simulation)"
_BOTH_PLATFORMS = "Both"


class _FunctionalWorker(QObject):
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


class _UnityRunWorker(QObject):
    """Runs one or more Unity test platforms sequentially on a worker thread.

    Emits per-platform so a failure on one platform (e.g. PlayMode timing out)
    doesn't hide a result already obtained from another (e.g. EditMode).
    """

    platform_started = Signal(str)
    platform_done = Signal(str, object)  # platform, TestReview
    platform_failed = Signal(str, str)  # platform, message
    finished = Signal()

    def __init__(self, services: Services, project, editor_path: str, platforms: list[str]) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._editor_path = editor_path
        self._platforms = platforms

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
        except Exception as exc:
            self.platform_failed.emit(
                self._platforms[0], f"Could not set up the AI provider: {exc}"
            )
            self.finished.emit()
            return
        if not provider.is_available():
            # Checked before launching Unity at all: a run can take a long time, and
            # there's no point spending it only to fail on the AI review afterward.
            self.platform_failed.emit(
                self._platforms[0],
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file, or switch to the Mock provider in Settings, before running "
                "tests — this is checked first so a run isn't wasted.",
            )
            self.finished.emit()
            return

        for platform in self._platforms:
            self.platform_started.emit(platform)
            try:
                result = run_tests(self._editor_path, self._project.path, platform)
                if not result.succeeded:
                    message = result.error or "Unity did not produce a results file."
                    if result.log_tail:
                        message += f"\n\nLog excerpt:\n{result.log_tail}"
                    self.platform_failed.emit(platform, message)
                    continue
                review = self._services.testing.analyze(
                    provider,
                    result.results_xml,
                    project=self._project,
                    source_type=SOURCE_UNITY_RUN,
                    source_filename=f"unity-{platform.lower()}-run.xml",
                    record_usage=self._services.usage.record_prompt,
                )
                self.platform_done.emit(platform, review)
            except ProviderNotReadyError as exc:
                self.platform_failed.emit(platform, str(exc))
            except Exception as exc:  # surfaced calmly to the user
                self.platform_failed.emit(platform, f"Something went wrong: {exc}")
        self.finished.emit()


class _PerformanceWorker(QObject):
    done = Signal(object)  # PerformanceReview
    failed = Signal(str)

    def __init__(
        self,
        services: Services,
        text: str,
        source_type: str,
        source_filename: str | None,
        target_hardware: str | None,
    ) -> None:
        super().__init__()
        self._services = services
        self._text = text
        self._source_type = source_type
        self._source_filename = source_filename
        self._target_hardware = target_hardware

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.performance.analyze(
                provider,
                self._text,
                project=self._services.active_project(),
                target_hardware=self._target_hardware,
                source_type=self._source_type,
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
            )
            self.done.emit(review)
        except PerformanceNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Something went wrong during analysis: {exc}")


class _AccessibilityWorker(QObject):
    done = Signal(object)  # AccessibilityReview
    failed = Signal(str)

    def __init__(
        self, services: Services, text: str, source_type: str, source_filename: str | None
    ) -> None:
        super().__init__()
        self._services = services
        self._text = text
        self._source_type = source_type
        self._source_filename = source_filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.accessibility.analyze(
                provider,
                self._text,
                project=self._services.active_project(),
                source_type=self._source_type,
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
            )
            self.done.emit(review)
        except AccessibilityNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Something went wrong during analysis: {exc}")


class TestingScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._pending_filename: str | None = None
        self._selected_case_id: int | None = None
        self._selected_issue_id: int | None = None
        self._perf_pending_filename: str | None = None
        self._access_pending_filename: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        header = QVBoxLayout()
        header.setContentsMargins(28, 28, 28, 0)
        title = QLabel("Automated Testing")
        title.setObjectName("ScreenTitle")
        header.addWidget(title)
        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        header.addWidget(self._context_label)
        outer.addLayout(header)

        self._tabs = QTabWidget()
        outer.addWidget(self._tabs, 1)
        self._tabs.addTab(self._build_functional_tab(), "Functional")
        self._tabs.addTab(self._build_performance_tab(), "Performance")
        self._tabs.addTab(self._build_accessibility_tab(), "Accessibility")

        self.refresh()

    def _scrollable(self) -> tuple[QWidget, QVBoxLayout]:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 12, 28, 28)
        layout.setSpacing(12)
        return container, layout

    # --- Functional tab ------------------------------------------------

    def _build_functional_tab(self) -> QWidget:
        container, layout = self._scrollable()
        self._build_case_form(layout)
        self._build_case_list(layout)
        self._build_unity_run(layout)
        self._build_analyze(layout)
        self._build_known_issues(layout)
        return container

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

        self._cases_empty = QLabel("No test cases yet. Add one above.")
        self._cases_empty.setObjectName("Muted")
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

    def _build_unity_run(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Run Unity tests")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Opt-in per project (Projects screen). Launches your project's Unity Editor "
            "headlessly to run its own tests, then feeds the results into the same review "
            "and Known Issues matching as a pasted result — nothing else about how Spiced "
            "handles results changes."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._unity_run_status = QLabel()
        self._unity_run_status.setObjectName("Muted")
        self._unity_run_status.setWordWrap(True)
        layout.addWidget(self._unity_run_status)

        row = QHBoxLayout()
        row.addWidget(QLabel("Platform:"))
        self._unity_platform_input = QComboBox()
        self._unity_platform_input.addItems([EDIT_MODE, PLAY_MODE, _BOTH_PLATFORMS])
        row.addWidget(self._unity_platform_input)
        row.addStretch(1)
        self._unity_run_btn = QPushButton("Run Tests Now")
        self._unity_run_btn.clicked.connect(self._on_run_unity_tests)
        row.addWidget(self._unity_run_btn)
        layout.addLayout(row)

        self._unity_run_result = QTextEdit()
        self._unity_run_result.setReadOnly(True)
        self._unity_run_result.setPlaceholderText(
            "Unity test-run output and review will appear here."
        )
        self._unity_run_result.setFixedHeight(180)
        layout.addWidget(self._unity_run_result)

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

    def _build_known_issues(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Known Issues")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Bugs Spiced has flagged before, from debugging sessions and test failures. New "
            "failures are checked against this list so repeats surface as \"this resembles a "
            "bug from before\" instead of starting from scratch."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._issues_list = QListWidget()
        self._issues_list.setFixedHeight(140)
        self._issues_list.currentItemChanged.connect(self._on_issue_selected)
        layout.addWidget(self._issues_list)

        self._issues_empty = QLabel("No known issues tracked for this project yet.")
        self._issues_empty.setObjectName("Muted")
        layout.addWidget(self._issues_empty)

        row = QHBoxLayout()
        row.addStretch(1)
        self._resolve_btn = QPushButton("Mark resolved")
        self._resolve_btn.clicked.connect(self._on_mark_resolved)
        row.addWidget(self._resolve_btn)
        self._reopen_btn = QPushButton("Reopen")
        self._reopen_btn.clicked.connect(self._on_mark_open)
        row.addWidget(self._reopen_btn)
        layout.addLayout(row)

    # --- Performance tab -------------------------------------------------

    def _build_performance_tab(self) -> QWidget:
        container, layout = self._scrollable()

        heading = QLabel("Performance & Profiling")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Paste or import numbers you already gathered (fps, memory, load time per "
            "location) as text, CSV, or JSON — Spiced never profiles your build itself. "
            "Optionally estimate a target hardware tier from those numbers (a simulation, "
            "not a real device test)."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._perf_input = QPlainTextEdit()
        self._perf_input.setPlaceholderText(
            "e.g. Waterfall Area: fps=42, memory=850MB, load=3.2s"
        )
        self._perf_input.setFixedHeight(120)
        layout.addWidget(self._perf_input)

        hw_row = QHBoxLayout()
        hw_row.addWidget(QLabel("Target hardware:"))
        self._hardware_input = QComboBox()
        self._hardware_input.addItem(_NO_HARDWARE)
        self._hardware_input.addItems(available_tiers())
        hw_row.addWidget(self._hardware_input, 1)
        layout.addLayout(hw_row)

        row = QHBoxLayout()
        self._perf_import_btn = QPushButton("Import performance file…")
        self._perf_import_btn.clicked.connect(self._on_perf_import)
        row.addWidget(self._perf_import_btn)
        row.addStretch(1)
        self._perf_analyze_btn = QPushButton("Analyze")
        self._perf_analyze_btn.clicked.connect(self._on_perf_analyze)
        row.addWidget(self._perf_analyze_btn)
        layout.addLayout(row)

        self._perf_result = QTextEdit()
        self._perf_result.setReadOnly(True)
        self._perf_result.setPlaceholderText("Your performance review will appear here.")
        self._perf_result.setFixedHeight(220)
        layout.addWidget(self._perf_result)

        history_title = QLabel("Recent performance reports")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._perf_history = QTextEdit()
        self._perf_history.setReadOnly(True)
        self._perf_history.setFixedHeight(110)
        layout.addWidget(self._perf_history)

        return container

    # --- Accessibility tab -------------------------------------------------

    def _build_accessibility_tab(self) -> QWidget:
        container, layout = self._scrollable()

        heading = QLabel("Accessibility Pass")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Paste a small JSON description of your HUD colors, audio captions, and control/"
            "text-scaling support. Spiced runs real WCAG contrast math and a colorblind-"
            "simulation check locally, then scores the checklist — never a shaming grade."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        example = QLabel(
            '{"hud_elements": [{"name": "HealthBar", "foreground": "#FF4040", '
            '"background": "#550000"}], "audio_files": [{"name": "vo_01.wav", '
            '"captioned": true}], "controls_remappable": true, "text_scaling_supported": false}'
        )
        example.setObjectName("Muted")
        example.setWordWrap(True)
        layout.addWidget(example)

        self._access_input = QPlainTextEdit()
        self._access_input.setPlaceholderText("Paste accessibility checklist JSON here…")
        self._access_input.setFixedHeight(120)
        layout.addWidget(self._access_input)

        row = QHBoxLayout()
        self._access_import_btn = QPushButton("Import checklist file…")
        self._access_import_btn.clicked.connect(self._on_access_import)
        row.addWidget(self._access_import_btn)
        row.addStretch(1)
        self._access_analyze_btn = QPushButton("Analyze")
        self._access_analyze_btn.clicked.connect(self._on_access_analyze)
        row.addWidget(self._access_analyze_btn)
        layout.addLayout(row)

        self._access_result = QTextEdit()
        self._access_result.setReadOnly(True)
        self._access_result.setPlaceholderText("Your accessibility review will appear here.")
        self._access_result.setFixedHeight(220)
        layout.addWidget(self._access_result)

        history_title = QLabel("Recent accessibility passes")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._access_history = QTextEdit()
        self._access_history.setReadOnly(True)
        self._access_history.setFixedHeight(110)
        layout.addWidget(self._access_history)

        return container

    # --- Refresh & state ---------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        has_project = project is not None
        if not has_project:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to "
                "add test cases and save results."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")

        for widget in (self._add_btn, self._title_input, self._update_status_btn):
            widget.setEnabled(has_project)

        self._refresh_cases()
        self._refresh_history()
        self._refresh_known_issues()
        self._refresh_perf_history()
        self._refresh_access_history()
        self._refresh_unity_run_status()
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
        has_issue = self._selected_issue_id is not None
        self._resolve_btn.setEnabled(has_issue)
        self._reopen_btn.setEnabled(has_issue)

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
            self._history.setPlainText("No test runs saved for this project yet.")
            return
        lines = []
        for run in runs:
            s = run.parsed_summary
            counts = f"{s.get('passed', 0)} passed / {s.get('failed', 0)} failed"
            name = f" · {run.source_filename}" if run.source_filename else ""
            summary = run.ai_summary or ""
            lines.append(f"[{run.created_at}]{name} · {counts}\n    {summary}")
        self._history.setPlainText("\n".join(lines))

    def _refresh_known_issues(self) -> None:
        self._issues_list.blockSignals(True)
        self._issues_list.clear()
        project = self._services.active_project()
        issues = self._services.testing.known_issues(project.id) if project else []
        for issue in issues:
            when = issue.resolved_at or issue.last_seen_at
            label = (
                f"[{issue.status}] {issue.title}  ·  seen {issue.occurrences}x  ·  "
                f"{'resolved ' if issue.status == STATUS_RESOLVED else 'last seen '}{when}"
            )
            item = QListWidgetItem(label)
            item.setData(_USER_ROLE, issue.id)
            self._issues_list.addItem(item)
        self._issues_list.blockSignals(False)
        self._issues_empty.setVisible(not issues)
        self._issues_list.setVisible(bool(issues))
        self._selected_issue_id = None
        self._update_edit_buttons()

    def _refresh_perf_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._perf_history.setPlainText(
                "Performance reports are saved once you select a project."
            )
            return
        reports = self._services.performance.history(project.id, limit=10)
        if not reports:
            self._perf_history.setPlainText("No performance reports saved for this project yet.")
            return
        lines = []
        for r in reports:
            s = r.parsed_summary
            hw = f" · {r.target_hardware}" if r.target_hardware else ""
            lines.append(
                f"[{r.created_at}]{hw} · avg {s.get('avg_fps')} fps · {len(r.spikes)} spike(s)\n"
                f"    {r.ai_summary or ''}"
            )
        self._perf_history.setPlainText("\n".join(lines))

    def _refresh_access_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._access_history.setPlainText(
                "Accessibility passes are saved once you select a project."
            )
            return
        reports = self._services.accessibility.history(project.id, limit=10)
        if not reports:
            self._access_history.setPlainText("No accessibility passes saved for this project yet.")
            return
        lines = []
        for r in reports:
            score = f"{r.score}/100" if r.score is not None else "n/a"
            lines.append(f"[{r.created_at}] score {score}\n    {r.ai_summary or ''}")
        self._access_history.setPlainText("\n".join(lines))

    def _refresh_unity_run_status(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._unity_run_status.setText("Select a project to run its Unity tests.")
            self._unity_run_btn.setEnabled(False)
            return
        if not project.unity_test_run_enabled:
            self._unity_run_status.setText(
                "Not enabled for this project. Turn on \"Allow Spiced to run this project's "
                "Unity tests\" on the Projects screen."
            )
            self._unity_run_btn.setEnabled(False)
            return
        if not project.path:
            self._unity_run_status.setText("Connect a Unity folder for this project first.")
            self._unity_run_btn.setEnabled(False)
            return
        required_version = project.engine_metadata.get("unity_version")
        editor = resolve_unity_editor(required_version, project.unity_editor_path_override)
        if editor is None:
            self._unity_run_status.setText(
                f"Unity {required_version or '(unknown version)'} isn't available. Install it "
                "via Unity Hub, or set a manual Editor path on the Projects screen."
            )
            self._unity_run_btn.setEnabled(False)
            return
        self._unity_run_status.setText(f"Will run Unity {editor.version} at {editor.path}")
        self._unity_run_btn.setEnabled(True)

    # --- Functional handlers -------------------------------------------------

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
        self._worker = _FunctionalWorker(self._services, results_text, source_type, filename)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, review: TestReview) -> None:
        text = review.response_text
        matches = [o for o in review.regression_outcomes if o.match is not None]
        if matches:
            lines = ["", "Known-issue matches:"]
            lines.extend(f"- {o.match.note}" for o in matches)
            text = text + "\n" + "\n".join(lines)
        self._result.setPlainText(text)
        self._pending_filename = None
        self._set_busy(False)
        self.usage_changed.emit()
        self._refresh_history()
        self._refresh_known_issues()

    def _on_failed(self, message: str) -> None:
        self._result.setPlainText(message)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._analyze_btn.setEnabled(not busy)
        self._analyze_btn.setText("Analyzing…" if busy else "Analyze")

    # --- Run Unity tests handlers --------------------------------------------

    def _on_run_unity_tests(self) -> None:
        project = self._services.active_project()
        if project is None or not project.unity_test_run_enabled or not project.path:
            return
        required_version = project.engine_metadata.get("unity_version")
        editor = resolve_unity_editor(required_version, project.unity_editor_path_override)
        if editor is None:
            QMessageBox.information(
                self,
                "Unity Editor not found",
                "Spiced couldn't resolve a Unity Editor to run — see the status above.",
            )
            return

        platform_choice = self._unity_platform_input.currentText()
        if platform_choice == _BOTH_PLATFORMS:
            platforms = [EDIT_MODE, PLAY_MODE]
        else:
            platforms = [platform_choice]

        self._unity_run_btn.setEnabled(False)
        self._unity_platform_input.setEnabled(False)
        self._unity_run_result.setPlainText(
            "Launching Unity — this can take a while, especially on a first run…"
        )

        self._thread = QThread()
        self._worker = _UnityRunWorker(self._services, project, editor.path, platforms)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.platform_started.connect(self._on_unity_platform_started)
        self._worker.platform_done.connect(self._on_unity_platform_done)
        self._worker.platform_failed.connect(self._on_unity_platform_failed)
        self._worker.finished.connect(self._on_unity_run_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_unity_platform_started(self, platform: str) -> None:
        self._unity_run_result.append(f"\n--- Running {platform} tests… ---")

    def _on_unity_platform_done(self, platform: str, review: TestReview) -> None:
        text = f"[{platform}] {review.response_text}"
        matches = [o for o in review.regression_outcomes if o.match is not None]
        if matches:
            lines = ["", "Known-issue matches:"]
            lines.extend(f"- {o.match.note}" for o in matches)
            text = text + "\n" + "\n".join(lines)
        self._unity_run_result.append(text)
        self.usage_changed.emit()
        self._refresh_history()
        self._refresh_known_issues()

    def _on_unity_platform_failed(self, platform: str, message: str) -> None:
        self._unity_run_result.append(f"[{platform}] {message}")

    def _on_unity_run_finished(self) -> None:
        self._unity_run_btn.setEnabled(True)
        self._unity_platform_input.setEnabled(True)

    # --- Known Issues handlers ----------------------------------------------

    def _on_issue_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        self._selected_issue_id = int(current.data(_USER_ROLE)) if current is not None else None
        self._update_edit_buttons()

    def _on_mark_resolved(self) -> None:
        if self._selected_issue_id is None:
            return
        self._services.testing.mark_issue_resolved(self._selected_issue_id)
        self._refresh_known_issues()

    def _on_mark_open(self) -> None:
        if self._selected_issue_id is None:
            return
        self._services.testing.mark_issue_open(self._selected_issue_id)
        self._refresh_known_issues()

    # --- Performance handlers ------------------------------------------------

    def _on_perf_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import performance data", "", "Data files (*.txt *.csv *.json);;All files (*)"
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
        self._perf_input.setPlainText(text)
        self._perf_pending_filename = Path(path).name

    def _on_perf_analyze(self) -> None:
        text = self._perf_input.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste or import performance data first."
            )
            return
        hardware = self._hardware_input.currentText()
        target_hardware = None if hardware == _NO_HARDWARE else hardware
        source_type = SOURCE_FILE if self._perf_pending_filename else SOURCE_PASTE
        filename = self._perf_pending_filename
        self._perf_analyze_btn.setEnabled(False)
        self._perf_analyze_btn.setText("Analyzing…")
        self._perf_result.setPlainText("Reading the numbers and thinking it through…")

        self._thread = QThread()
        self._worker = _PerformanceWorker(
            self._services, text, source_type, filename, target_hardware
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_perf_done)
        self._worker.failed.connect(self._on_perf_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_perf_done(self, review: PerformanceReview) -> None:
        self._perf_result.setPlainText(review.response_text)
        self._perf_pending_filename = None
        self._perf_analyze_btn.setEnabled(True)
        self._perf_analyze_btn.setText("Analyze")
        self.usage_changed.emit()
        self._refresh_perf_history()

    def _on_perf_failed(self, message: str) -> None:
        self._perf_result.setPlainText(message)
        self._perf_analyze_btn.setEnabled(True)
        self._perf_analyze_btn.setText("Analyze")

    # --- Accessibility handlers ------------------------------------------------

    def _on_access_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import accessibility checklist", "", "JSON files (*.json);;All files (*)"
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
        self._access_input.setPlainText(text)
        self._access_pending_filename = Path(path).name

    def _on_access_analyze(self) -> None:
        text = self._access_input.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Nothing to analyze", "Paste or import checklist JSON first."
            )
            return
        source_type = SOURCE_FILE if self._access_pending_filename else SOURCE_PASTE
        filename = self._access_pending_filename
        self._access_analyze_btn.setEnabled(False)
        self._access_analyze_btn.setText("Analyzing…")
        self._access_result.setPlainText("Running the checklist and thinking it through…")

        self._thread = QThread()
        self._worker = _AccessibilityWorker(self._services, text, source_type, filename)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_access_done)
        self._worker.failed.connect(self._on_access_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_access_done(self, review: AccessibilityReview) -> None:
        self._access_result.setPlainText(review.response_text)
        self._access_pending_filename = None
        self._access_analyze_btn.setEnabled(True)
        self._access_analyze_btn.setText("Analyze")
        self.usage_changed.emit()
        self._refresh_access_history()

    def _on_access_failed(self, message: str) -> None:
        self._access_result.setPlainText(message)
        self._access_analyze_btn.setEnabled(True)
        self._access_analyze_btn.setText("Analyze")
