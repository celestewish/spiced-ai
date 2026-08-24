"""Feedback Review: theme cards, AI review, task drafts, and Community Pulse.

Local parsing and heuristic classification work fully offline with no AI
provider — the developer can always preview theme cards before spending a
prompt. The AI review and Community Pulse check-ins run the selected provider
on a worker thread; only a trimmed excerpt and local counts are ever sent —
never project files.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.community_pulse import CommunityPulseResult, SourceNotReadyError
from spiced.core.community_pulse import ProviderNotReadyError as PulseProviderNotReadyError
from spiced.core.feedback import SOURCE_FILE, SOURCE_PASTE, FeedbackReview, ProviderNotReadyError
from spiced.core.playtester_recruitment import ProviderNotReadyError as RecruitNotReadyError
from spiced.core.playtester_recruitment import RecruitmentDraftResult
from spiced.storage.feedback_tasks import STATUS_ACCEPTED, STATUS_DISMISSED
from spiced.storage.playtester_signups import STATUSES as SIGNUP_STATUSES
from spiced.ui.thread_utils import AIStreamWorker, launch_worker
from spiced.ui.widgets.accordion import AccordionSection
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.scroll_safe_combo_box import ScrollSafeComboBox
from spiced.ui.widgets.source_link import SourceLinkExpander

_THEME_GRID_COLUMNS = 3


def _card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(8)
    shadow = QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(20)
    shadow.setOffset(0, 5)
    shadow.setColor(QColor(20, 10, 40, 80))
    frame.setGraphicsEffect(shadow)
    return frame

_USER_ROLE = 0x0100


def _append_chunk(widget: QTextEdit, text: str) -> None:
    """Append streamed text to a result widget in place -- see the
    equivalent helper in ui.screens.debugging for the full rationale."""
    cursor = widget.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText(text)
    widget.setTextCursor(cursor)


class _AnalyzeWorker(AIStreamWorker):
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

    def _call(self, on_chunk):
        provider = self._services.build_provider()
        project = self._services.active_project()
        team_mode = self._services.team_mode_enabled()
        review = self._services.feedback.analyze(
            provider,
            self._feedback_text,
            project=project,
            source_type=self._source_type,
            source_label=self._source_label,
            source_filename=self._source_filename,
            record_usage=self._services.usage.record_prompt,
            team_mode=team_mode,
            team_members=self._services.team_prompt_context(project) if team_mode else None,
            on_chunk=on_chunk,
        )
        # Opt-In Only Telemetry (Phase C): a bare, anonymous event name —
        # never the feedback content itself. No-op unless enabled.
        self._services.record_telemetry_event("feedback.analysis_run")
        return review

    def expected_errors(self):
        return (ProviderNotReadyError,)

    def error_message(self, exc: Exception) -> str:
        return f"Something went wrong during analysis: {exc}"


class _PulseWorker(AIStreamWorker):
    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services

    def _call(self, on_chunk):
        provider = self._services.build_provider()
        source = self._services.build_community_source()
        return self._services.community_pulse.check_in(
            provider,
            source,
            project=self._services.active_project(),
            record_usage=self._services.usage.record_prompt,
            on_chunk=on_chunk,
        )

    def expected_errors(self):
        return (SourceNotReadyError, PulseProviderNotReadyError)

    def error_message(self, exc: Exception) -> str:
        return f"Something went wrong during the check-in: {exc}"


class _RecruitmentWorker(AIStreamWorker):
    def __init__(
        self, services: Services, needs_description: str, target_platform: str, timeframe: str
    ) -> None:
        super().__init__()
        self._services = services
        self._needs_description = needs_description
        self._target_platform = target_platform
        self._timeframe = timeframe

    def _call(self, on_chunk):
        provider = self._services.build_provider()
        result = self._services.playtester_recruitment.draft_post(
            provider,
            needs_description=self._needs_description,
            target_platform=self._target_platform,
            timeframe=self._timeframe,
            project=self._services.active_project(),
            record_usage=self._services.usage.record_prompt,
            on_chunk=on_chunk,
        )
        self._services.record_telemetry_event("feedback.playtester_recruitment_draft_run")
        return result

    def expected_errors(self):
        return (RecruitNotReadyError,)

    def error_message(self, exc: Exception) -> str:
        return f"Something went wrong while drafting the post: {exc}"


_SIGNUP_USER_ROLE = 0x0101


class FeedbackScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._pending_filename: str | None = None
        self._last_batch_id: int | None = None

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
        layout.setSpacing(12)

        title = QLabel("Feedback Review")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        input_card = _card()
        self._build_input(input_card.layout())
        layout.addWidget(input_card)

        themes_card = _card()
        self._build_theme_cards(themes_card.layout())
        layout.addWidget(themes_card)

        # Drafted Tasks + AI Review: both are "what happened as a result of
        # the themes above," so they sit side by side rather than each
        # getting a full-width section. Recent feedback batches (formerly
        # its own full-width section, _build_history) folds into the AI
        # Review card, right under its result box.
        two_up = QHBoxLayout()
        two_up.setSpacing(14)
        tasks_card = _card()
        self._build_tasks(tasks_card.layout())
        two_up.addWidget(tasks_card, 1)
        review_card = _card()
        review_layout = review_card.layout()
        self._build_ai_review(review_layout)
        self._build_history(review_layout)
        two_up.addWidget(review_card, 1)
        layout.addLayout(two_up)

        recruit_accordion = AccordionSection("Recruit Playtesters")
        self._build_playtester_recruitment(recruit_accordion.body_layout)
        layout.addWidget(recruit_accordion)

        pulse_accordion = AccordionSection("Community Pulse")
        self._pulse_status_pill = QLabel("Off")
        self._pulse_status_pill.setObjectName("StatusPill")
        self._pulse_status_pill.setProperty("state", "off")
        pulse_accordion.header_extra.addWidget(self._pulse_status_pill)
        self._build_community_pulse(pulse_accordion.body_layout, pulse_accordion)
        layout.addWidget(pulse_accordion)

        self.refresh()

    # --- Input -------------------------------------------------------------

    def _build_input(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Add feedback")
        heading.setObjectName("CardTitle")
        heading.setToolTip(
            "Paste playtester comments or import a .txt/.md/.csv/.json file. Spiced parses it "
            "locally, groups it into theme cards, and separates bugs from design preferences — "
            "it never scrapes anything and never decides your design for you."
        )
        layout.addWidget(heading)

        label_row = QHBoxLayout()
        label_row.addWidget(QLabel("Source:"))
        self._label_input = QLineEdit()
        self._label_input.setPlaceholderText("e.g. Playtest 1, Discord, Survey, itch.io comments")
        label_row.addWidget(self._label_input, 1)
        layout.addLayout(label_row)

        self._feedback_input = QPlainTextEdit()
        self._feedback_input.setPlaceholderText("Paste player feedback here…")
        self._feedback_input.setFixedHeight(80)
        layout.addWidget(self._feedback_input)

        row = QHBoxLayout()
        self._import_btn = PillButton("Import feedback file…")
        self._import_btn.clicked.connect(self._on_import)
        row.addWidget(self._import_btn)
        self._preview_btn = PillButton("Preview (local only)")
        self._preview_btn.clicked.connect(self._on_preview)
        row.addWidget(self._preview_btn)
        row.addStretch(1)
        self._analyze_btn = PillButton("Analyze", water_fill=True)
        self._analyze_btn.clicked.connect(self._on_analyze)
        row.addWidget(self._analyze_btn)
        layout.addLayout(row)

    # --- Theme cards (default landing view once feedback is parsed) --------

    def _build_theme_cards(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Themes")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)

        self._theme_hint = QLabel(
            "Preview or Analyze feedback above to see theme cards sorted by frequency."
        )
        self._theme_hint.setObjectName("Muted")
        self._theme_hint.setWordWrap(True)
        layout.addWidget(self._theme_hint)

        # The visual centerpiece of the screen -- a wrapping grid
        # (repeat(auto-fit, minmax(240px,1fr)) in the design handoff) rather
        # than a single-column QListWidget, since this is what a dev opens
        # the screen to see.
        self._theme_grid_widget = QWidget()
        self._theme_grid = QGridLayout(self._theme_grid_widget)
        self._theme_grid.setSpacing(14)
        self._theme_grid_widget.setVisible(False)
        layout.addWidget(self._theme_grid_widget)

    def _refresh_theme_cards(self, cards) -> None:
        while self._theme_grid.count():
            item = self._theme_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._theme_hint.setVisible(not cards)
        self._theme_grid_widget.setVisible(bool(cards))
        for index, card in enumerate(cards):
            row, col = divmod(index, _THEME_GRID_COLUMNS)
            self._theme_grid.addWidget(self._theme_card_widget(card), row, col)

    def _theme_card_widget(self, card) -> QWidget:
        widget = _card()
        col = widget.layout()

        heading = QLabel(card.category)
        heading.setObjectName("CardTitle")
        col.addWidget(heading)
        caption = QLabel(f"{card.percentage:g}% of comments ({card.count})")
        caption.setObjectName("Muted")
        col.addWidget(caption)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(round(max(0.0, min(100.0, card.percentage))))
        bar.setTextVisible(False)
        col.addWidget(bar)

        if card.representative_text:
            example = QLabel(f"“{card.representative_text[:140]}”")
            example.setObjectName("Muted")
            example.setWordWrap(True)
            col.addWidget(example)

        task_btn = PillButton("Turn into task")
        task_btn.clicked.connect(lambda _checked=False, c=card: self._on_turn_into_task(c))
        col.addWidget(task_btn)
        return widget

    def _on_turn_into_task(self, card) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._services.feedback.draft_task(
            project.id, card.category, card.representative_text or "", batch_id=self._last_batch_id
        )
        self._refresh_tasks()

    # --- Drafted tasks -------------------------------------------------------

    def _build_tasks(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Drafted tasks")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Short, editable drafts from theme cards — accept, edit, or copy them to your own "
            "tracker. Spiced doesn't manage a task list itself."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._task_list = QListWidget()
        self._task_list.setFixedHeight(140)
        layout.addWidget(self._task_list)

        self._tasks_empty = QLabel("No drafted tasks yet — use “Turn into task” on a theme card.")
        self._tasks_empty.setObjectName("Muted")
        layout.addWidget(self._tasks_empty)

    def _refresh_tasks(self) -> None:
        project = self._services.active_project()
        tasks = self._services.feedback.list_tasks(project.id) if project else []
        self._task_list.clear()
        self._tasks_empty.setVisible(not tasks)
        self._task_list.setVisible(bool(tasks))
        for task in tasks:
            widget = self._task_widget(task)
            item = QListWidgetItem()
            self._task_list.addItem(item)
            item.setSizeHint(widget.sizeHint())
            self._task_list.setItemWidget(item, widget)

    def _task_widget(self, task) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(6, 4, 6, 4)

        label = QLabel(f"[{task.status}] {task.text}")
        label.setWordWrap(True)
        row.addWidget(label, 1)

        edit_btn = PillButton("Edit")
        edit_btn.clicked.connect(lambda _checked=False, t=task: self._on_edit_task(t))
        row.addWidget(edit_btn)

        accept_btn = PillButton("Accept")
        accept_btn.clicked.connect(
            lambda _checked=False, t=task: self._on_task_status(t, STATUS_ACCEPTED)
        )
        row.addWidget(accept_btn)

        copy_btn = PillButton("Copy")
        copy_btn.clicked.connect(lambda _checked=False, t=task: self._on_copy_task(t))
        row.addWidget(copy_btn)

        dismiss_btn = PillButton("Dismiss")
        dismiss_btn.clicked.connect(
            lambda _checked=False, t=task: self._on_task_status(t, STATUS_DISMISSED)
        )
        row.addWidget(dismiss_btn)

        delete_btn = PillButton("Delete")
        delete_btn.clicked.connect(lambda _checked=False, t=task: self._on_delete_task(t))
        row.addWidget(delete_btn)
        return widget

    def _on_edit_task(self, task) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "Edit task", "Task text:", task.text)
        if ok and text.strip():
            self._services.feedback.update_task(task.id, text.strip())
            self._refresh_tasks()

    def _on_task_status(self, task, status: str) -> None:
        self._services.feedback.set_task_status(task.id, status)
        self._refresh_tasks()

    def _on_copy_task(self, task) -> None:
        QApplication.clipboard().setText(task.text)

    def _on_delete_task(self, task) -> None:
        self._services.feedback.delete_task(task.id)
        self._refresh_tasks()

    # --- AI review -----------------------------------------------------------

    def _build_ai_review(self, layout: QVBoxLayout) -> None:
        heading = QLabel("AI review")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        self._result = QTextEdit()
        self._result.setReadOnly(True)
        self._result.setPlaceholderText(
            "Your structured feedback review will appear here. Use Preview to see theme cards "
            "and category counts without an AI provider."
        )
        self._result.setFixedHeight(220)
        layout.addWidget(self._result)

        # Transparent AI Reasoning (Phase C): which entries/excerpt this
        # review was actually built from. Theme cards above already carry
        # their own per-category representative quote, so this covers the
        # batch-level "why" rather than duplicating a link on every card.
        self._source_link = SourceLinkExpander()
        layout.addWidget(self._source_link)

    def _build_history(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Recent feedback batches")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setFixedHeight(110)
        layout.addWidget(self._history)

    # --- Recruit Playtesters (Playtester Recruitment Assistant) --------------

    def _build_playtester_recruitment(self, layout: QVBoxLayout) -> None:
        intro = QLabel(
            "Describe what you need testers for, the target platform, and a timeframe — Spiced "
            "drafts a short recruitment post for you to copy and post yourself (Discord, "
            "forums, an itch devlog, wherever). Sign-up tracking below is a simple local list "
            "you maintain by hand — Spiced has no build-distribution system and never sends "
            "anything (no emails, no build links) on your behalf."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._recruit_needs_input = QLineEdit()
        self._recruit_needs_input.setPlaceholderText(
            "What do you need testers for? e.g. \"new co-op mode before Early Access launch\""
        )
        layout.addWidget(self._recruit_needs_input)

        detail_row = QHBoxLayout()
        detail_row.addWidget(QLabel("Platform:"))
        self._recruit_platform_input = QLineEdit()
        self._recruit_platform_input.setPlaceholderText("e.g. Windows/Steam")
        detail_row.addWidget(self._recruit_platform_input, 1)
        detail_row.addWidget(QLabel("Timeframe:"))
        self._recruit_timeframe_input = QLineEdit()
        self._recruit_timeframe_input.setPlaceholderText("e.g. next 2 weeks")
        detail_row.addWidget(self._recruit_timeframe_input, 1)
        layout.addLayout(detail_row)

        row = QHBoxLayout()
        row.addStretch(1)
        self._recruit_draft_btn = PillButton("Draft recruitment post", water_fill=True)
        self._recruit_draft_btn.clicked.connect(self._on_recruit_draft)
        row.addWidget(self._recruit_draft_btn)
        layout.addLayout(row)

        self._recruit_result = QTextEdit()
        self._recruit_result.setReadOnly(True)
        self._recruit_result.setPlaceholderText("Your draft recruitment post will appear here.")
        self._recruit_result.setFixedHeight(140)
        layout.addWidget(self._recruit_result)

        signup_heading = QLabel("Sign-up list (local only)")
        signup_heading.setObjectName("SectionTitle")
        layout.addWidget(signup_heading)

        add_row = QHBoxLayout()
        self._signup_name_input = QLineEdit()
        self._signup_name_input.setPlaceholderText("Tester name")
        add_row.addWidget(self._signup_name_input, 1)
        self._signup_contact_input = QLineEdit()
        self._signup_contact_input.setPlaceholderText("Contact (email/handle, optional)")
        add_row.addWidget(self._signup_contact_input, 1)
        self._signup_add_btn = PillButton("Add")
        self._signup_add_btn.clicked.connect(self._on_signup_add)
        add_row.addWidget(self._signup_add_btn)
        layout.addLayout(add_row)

        self._signup_list = QListWidget()
        self._signup_list.setFixedHeight(120)
        self._signup_list.currentItemChanged.connect(self._on_signup_selected)
        layout.addWidget(self._signup_list)

        self._signups_empty = QLabel("No testers tracked yet — add one above.")
        self._signups_empty.setObjectName("Muted")
        layout.addWidget(self._signups_empty)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Set status:"))
        self._signup_status_input = ScrollSafeComboBox()
        self._signup_status_input.addItems(list(SIGNUP_STATUSES))
        status_row.addWidget(self._signup_status_input)
        self._signup_update_status_btn = PillButton("Update")
        self._signup_update_status_btn.clicked.connect(self._on_signup_update_status)
        status_row.addWidget(self._signup_update_status_btn)
        status_row.addStretch(1)
        self._signup_delete_btn = PillButton("Delete")
        self._signup_delete_btn.clicked.connect(self._on_signup_delete)
        status_row.addWidget(self._signup_delete_btn)
        layout.addLayout(status_row)
        self._selected_signup_id: int | None = None

    def _on_recruit_draft(self) -> None:
        self._recruit_draft_btn.setEnabled(False)
        self._recruit_draft_btn.setText("Drafting…")
        self._recruit_draft_btn.set_loading(True)
        self._recruit_result.clear()

        worker = _RecruitmentWorker(
            self._services,
            self._recruit_needs_input.text().strip(),
            self._recruit_platform_input.text().strip(),
            self._recruit_timeframe_input.text().strip(),
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.chunk.connect(self._on_recruit_chunk)
        worker.done.connect(self._on_recruit_done)
        worker.failed.connect(self._on_recruit_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_recruit_chunk(self, text: str) -> None:
        _append_chunk(self._recruit_result, text)

    def _on_recruit_done(self, result: RecruitmentDraftResult) -> None:
        self._recruit_draft_btn.setEnabled(True)
        self._recruit_draft_btn.setText("Draft recruitment post")
        self._recruit_draft_btn.set_loading(False)
        self._recruit_result.setPlainText(result.response_text)
        self.usage_changed.emit()

    def _on_recruit_failed(self, message: str) -> None:
        self._recruit_draft_btn.setEnabled(True)
        self._recruit_draft_btn.setText("Draft recruitment post")
        self._recruit_draft_btn.set_loading(False)
        self._recruit_result.setPlainText(message)

    def _on_signup_add(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        name = self._signup_name_input.text().strip()
        if not name:
            QMessageBox.information(self, "Name needed", "Enter a tester name first.")
            return
        self._services.playtester_recruitment.add_signup(
            project.id, name, self._signup_contact_input.text().strip() or None
        )
        self._signup_name_input.clear()
        self._signup_contact_input.clear()
        self._refresh_signups()

    def _on_signup_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        self._selected_signup_id = int(current.data(_SIGNUP_USER_ROLE)) if current else None

    def _on_signup_update_status(self) -> None:
        if self._selected_signup_id is None:
            QMessageBox.information(self, "Select a tester", "Pick a tester from the list.")
            return
        self._services.playtester_recruitment.set_status(
            self._selected_signup_id, self._signup_status_input.currentText()
        )
        self._refresh_signups()

    def _on_signup_delete(self) -> None:
        if self._selected_signup_id is None:
            return
        self._services.playtester_recruitment.delete_signup(self._selected_signup_id)
        self._selected_signup_id = None
        self._refresh_signups()

    def _refresh_signups(self) -> None:
        self._signup_list.blockSignals(True)
        self._signup_list.clear()
        project = self._services.active_project()
        signups = self._services.playtester_recruitment.list_signups(project.id) if project else []
        for signup in signups:
            contact = f" ({signup.contact})" if signup.contact else ""
            item = QListWidgetItem(f"[{signup.status}] {signup.name}{contact}")
            item.setData(_SIGNUP_USER_ROLE, signup.id)
            self._signup_list.addItem(item)
        self._signup_list.blockSignals(False)
        self._signups_empty.setVisible(not signups)
        self._signup_list.setVisible(bool(signups))

    # --- Community Pulse (opt-in, off by default) -----------------------------

    def _build_community_pulse(self, layout: QVBoxLayout, accordion: AccordionSection) -> None:
        self._pulse_accordion = accordion
        self._pulse_toggle = QCheckBox("Enable Community Pulse (opt-in)")
        self._pulse_toggle.toggled.connect(self._on_pulse_toggle)
        accordion.header_extra.addWidget(self._pulse_toggle)

        self._pulse_panel = QWidget()
        pulse_layout = QVBoxLayout(self._pulse_panel)
        pulse_layout.setContentsMargins(0, 6, 0, 0)
        pulse_layout.setSpacing(8)

        intro = QLabel(
            "Off by default. Reads recent messages from exactly one channel you choose and "
            "gives a light, high-level sentiment summary — always transparent about what was "
            "read, never scraping DMs."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        pulse_layout.addWidget(intro)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source:"))
        self._pulse_source = ScrollSafeComboBox()
        self._pulse_source.addItems(["mock", "discord"])
        self._pulse_source.currentTextChanged.connect(self._on_pulse_source_changed)
        source_row.addWidget(self._pulse_source, 1)
        self._pulse_run_btn = PillButton("Run pulse check-in", water_fill=True)
        self._pulse_run_btn.clicked.connect(self._on_pulse_run)
        source_row.addWidget(self._pulse_run_btn)
        pulse_layout.addLayout(source_row)

        self._pulse_result = QTextEdit()
        self._pulse_result.setReadOnly(True)
        self._pulse_result.setPlaceholderText("Your community pulse summary will appear here.")
        self._pulse_result.setFixedHeight(160)
        pulse_layout.addWidget(self._pulse_result)

        self._pulse_source_link = SourceLinkExpander()
        pulse_layout.addWidget(self._pulse_source_link)

        history_title = QLabel("Recent check-ins")
        history_title.setObjectName("SectionTitle")
        pulse_layout.addWidget(history_title)
        self._pulse_history = QTextEdit()
        self._pulse_history.setReadOnly(True)
        self._pulse_history.setFixedHeight(90)
        pulse_layout.addWidget(self._pulse_history)

        layout.addWidget(self._pulse_panel)

    def _on_pulse_toggle(self, checked: bool) -> None:
        self._services.set_community_pulse_enabled(checked)
        self._pulse_accordion.set_expanded(checked)
        self._sync_pulse_pill(checked)

    def _on_pulse_source_changed(self, name: str) -> None:
        self._services.set_community_source_name(name)

    def _on_pulse_run(self) -> None:
        self._pulse_run_btn.setEnabled(False)
        self._pulse_run_btn.setText("Reading…")
        self._pulse_run_btn.set_loading(True)
        self._pulse_result.clear()

        worker = _PulseWorker(self._services)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.chunk.connect(self._on_pulse_chunk)
        worker.done.connect(self._on_pulse_done)
        worker.failed.connect(self._on_pulse_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_pulse_chunk(self, text: str) -> None:
        _append_chunk(self._pulse_result, text)

    def _on_pulse_done(self, result: CommunityPulseResult) -> None:
        self._pulse_result.setPlainText(result.response_text)
        description = f"From {result.message_count} recent messages in {result.channel_label}."
        excerpt = result.checkin.raw_excerpt if result.checkin else None
        self._pulse_source_link.set_source(description, excerpt)
        self._pulse_run_btn.setEnabled(True)
        self._pulse_run_btn.setText("Run pulse check-in")
        self._pulse_run_btn.set_loading(False)
        self.usage_changed.emit()
        self._refresh_pulse_history()

    def _on_pulse_failed(self, message: str) -> None:
        self._pulse_result.setPlainText(message)
        self._pulse_source_link.set_source(None, None)
        self._pulse_run_btn.setEnabled(True)
        self._pulse_run_btn.setText("Run pulse check-in")
        self._pulse_run_btn.set_loading(False)

    def _refresh_pulse_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._pulse_history.setPlainText(
                "Check-ins are saved once you select an active project."
            )
            return
        checkins = self._services.community_pulse.history(project.id, limit=10)
        if not checkins:
            self._pulse_history.setPlainText("No check-ins saved for this project yet.")
            return
        lines = [
            f"[{c.created_at}] {c.channel_label} · {c.message_count} messages\n"
            f"    {c.ai_summary or ''}"
            for c in checkins
        ]
        self._pulse_history.setPlainText("\n".join(lines))

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

        pulse_enabled = self._services.community_pulse_enabled()
        self._pulse_toggle.blockSignals(True)
        self._pulse_toggle.setChecked(pulse_enabled)
        self._pulse_toggle.blockSignals(False)
        self._pulse_accordion.set_expanded(pulse_enabled)
        self._sync_pulse_pill(pulse_enabled)
        self._pulse_source.blockSignals(True)
        self._pulse_source.setCurrentText(self._services.community_source_name())
        self._pulse_source.blockSignals(False)

        self._refresh_history()
        self._refresh_tasks()
        self._refresh_signups()
        self._refresh_pulse_history()

    def _sync_pulse_pill(self, enabled: bool) -> None:
        self._pulse_status_pill.setText("On" if enabled else "Off")
        self._pulse_status_pill.setProperty("state", "on" if enabled else "off")
        self._pulse_status_pill.style().unpolish(self._pulse_status_pill)
        self._pulse_status_pill.style().polish(self._pulse_status_pill)

    def _refresh_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._history.setPlainText("Feedback batches are saved once you select a project.")
            return
        batches = self._services.feedback.history(project.id, limit=10)
        if not batches:
            self._history.setPlainText("No feedback batches saved for this project yet.")
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
            self, "Import feedback", "", "Feedback files (*.txt *.md *.csv *.json);;All files (*)"
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
        self._last_batch_id = None
        self._refresh_theme_cards(preview.theme_cards)
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
        lines.append("\nSee theme cards above. Click Analyze for the full AI review.")
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
        self._result.clear()

        worker = _AnalyzeWorker(
            self._services, text, source_type, label, self._pending_filename
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.chunk.connect(self._on_chunk)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_chunk(self, text: str) -> None:
        _append_chunk(self._result, text)

    def _on_done(self, review: FeedbackReview) -> None:
        self._result.setPlainText(review.response_text)
        self._last_batch_id = review.batch.id if review.batch else None
        self._refresh_theme_cards(review.theme_cards)
        source_bits = [f"{review.parsed.entry_count} feedback entries"]
        if review.batch and (review.batch.source_label or review.batch.source_filename):
            source_bits.append(review.batch.source_label or review.batch.source_filename)
        self._source_link.set_source(
            f"From {' — '.join(source_bits)}.", review.parsed.excerpt
        )
        self._pending_filename = None
        self._set_busy(False)
        self.usage_changed.emit()
        self._refresh_history()

    def _on_failed(self, message: str) -> None:
        self._result.setPlainText(message)
        self._source_link.set_source(None, None)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._analyze_btn.setEnabled(not busy and self._services.active_project() is not None)
        self._analyze_btn.setText("Analyzing…" if busy else "Analyze")
        self._analyze_btn.set_loading(busy)
