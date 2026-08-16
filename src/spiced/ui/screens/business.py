"""Business: Budget/Runway Tracker and Competitive Landscape Scan.

Two sections, following the established pattern: the runway arithmetic works
instantly with no AI provider; the Competitive Landscape Scan runs the
selected provider on a worker thread and is explicitly labeled approximate,
not live market data.

The Contract/License Checklist and Grant/Funding Finder previously lived
here too; both have been removed (product decisions): Spiced doesn't do
legal-adjacent features, and a grant search is something a developer can
just search for themselves.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.budget_tracker import RunwaySummary
from spiced.core.competitive_landscape import CompetitiveLandscapeResult
from spiced.core.competitive_landscape import ProviderNotReadyError as LandscapeNotReadyError
from spiced.storage.budget_entries import FREQUENCIES
from spiced.ui.thread_utils import AIStreamWorker, launch_worker
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.scroll_safe_combo_box import ScrollSafeComboBox

_USER_ROLE = 0x0100


def _append_chunk(widget: QTextEdit, text: str) -> None:
    """Append streamed text to a result widget in place -- see the
    equivalent helper in ui.screens.debugging for the full rationale."""
    cursor = widget.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText(text)
    widget.setTextCursor(cursor)


class _LandscapeWorker(AIStreamWorker):
    def __init__(self, services: Services, description: str) -> None:
        super().__init__()
        self._services = services
        self._description = description

    def _call(self, on_chunk):
        provider = self._services.build_provider()
        result = self._services.competitive_landscape.analyze(
            provider,
            self._description,
            project=self._services.active_project(),
            record_usage=self._services.usage.record_prompt,
            on_chunk=on_chunk,
        )
        self._services.record_telemetry_event("business.competitive_landscape_run")
        return result

    def expected_errors(self):
        return (LandscapeNotReadyError,)

    def error_message(self, exc: Exception) -> str:
        return f"Something went wrong during the scan: {exc}"


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


class BusinessScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._selected_budget_entry_id: int | None = None

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
        layout.setSpacing(14)

        title = QLabel("Business")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        budget_card = _card()
        self._build_budget_tracker(budget_card.layout())
        layout.addWidget(budget_card)

        hero = QFrame()
        hero.setObjectName("ToolHeroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        hero_layout.setSpacing(10)
        self._build_landscape_scan(hero_layout)
        layout.addWidget(hero)

        self.refresh()

    # --- Budget/Runway Tracker ----------------------------------------------

    def _build_budget_tracker(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Budget/Runway Tracker")
        heading.setObjectName("CardTitle")
        heading.setToolTip(
            "Your own offline expense tracking — not Spiced's billing (Spiced has none). "
            "Purely local arithmetic — works with no AI provider configured."
        )
        layout.addWidget(heading)

        funds_row = QHBoxLayout()
        funds_row.addWidget(QLabel("Funds available:"))
        self._funds_input = QLineEdit()
        self._funds_input.setPlaceholderText("e.g. 5000")
        funds_row.addWidget(self._funds_input, 1)
        self._funds_save_btn = PillButton("Save")
        self._funds_save_btn.clicked.connect(self._on_save_funds)
        funds_row.addWidget(self._funds_save_btn)
        layout.addLayout(funds_row)

        form_row = QHBoxLayout()
        self._budget_name_input = QLineEdit()
        self._budget_name_input.setPlaceholderText("e.g. Contractor pay, Unity Pro seat…")
        form_row.addWidget(self._budget_name_input, 2)
        self._budget_amount_input = QLineEdit()
        self._budget_amount_input.setPlaceholderText("Amount")
        form_row.addWidget(self._budget_amount_input, 1)
        self._budget_frequency_input = ScrollSafeComboBox()
        self._budget_frequency_input.addItems(list(FREQUENCIES))
        form_row.addWidget(self._budget_frequency_input, 1)
        self._budget_add_btn = PillButton("Add cost")
        self._budget_add_btn.clicked.connect(self._on_budget_add)
        form_row.addWidget(self._budget_add_btn)
        layout.addLayout(form_row)

        self._budget_list = QListWidget()
        self._budget_list.setFixedHeight(110)
        self._budget_list.currentItemChanged.connect(self._on_budget_selected)
        layout.addWidget(self._budget_list)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._budget_clear_btn = PillButton("New / clear", ghost=True)
        self._budget_clear_btn.clicked.connect(self._on_budget_clear)
        btn_row.addWidget(self._budget_clear_btn)
        self._budget_delete_btn = PillButton("Delete", ghost=True)
        self._budget_delete_btn.clicked.connect(self._on_budget_delete)
        btn_row.addWidget(self._budget_delete_btn)
        self._budget_save_btn = PillButton("Save changes")
        self._budget_save_btn.clicked.connect(self._on_budget_save)
        btn_row.addWidget(self._budget_save_btn)
        layout.addLayout(btn_row)

        # The number a dev opens this card to see -- pulled out into its own
        # aqua-tinted highlight box instead of a plain sentence at the bottom.
        self._runway_box = QFrame()
        self._runway_box.setObjectName("ReadinessCard")
        runway_layout = QVBoxLayout(self._runway_box)
        runway_layout.setContentsMargins(16, 12, 16, 12)
        runway_layout.setSpacing(2)
        runway_label = QLabel("Estimated runway")
        runway_label.setObjectName("StatLabel")
        runway_layout.addWidget(runway_label)
        self._runway_value = QLabel("—")
        self._runway_value.setObjectName("StatValue")
        runway_layout.addWidget(self._runway_value)
        self._runway_detail = QLabel()
        self._runway_detail.setObjectName("Muted")
        self._runway_detail.setWordWrap(True)
        runway_layout.addWidget(self._runway_detail)
        layout.addWidget(self._runway_box)

    def _on_save_funds(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        try:
            amount = float(self._funds_input.text().strip() or "0")
        except ValueError:
            QMessageBox.information(self, "Not a number", "Enter available funds as a number.")
            return
        try:
            self._services.budget_tracker.set_available_funds(project.id, amount)
        except ValueError as exc:
            QMessageBox.information(self, "Invalid amount", str(exc))
            return
        self._refresh_budget()

    def _on_budget_add(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        name = self._budget_name_input.text().strip()
        try:
            amount = float(self._budget_amount_input.text().strip() or "0")
        except ValueError:
            QMessageBox.information(self, "Not a number", "Enter the amount as a number.")
            return
        try:
            self._services.budget_tracker.add_entry(
                project.id, name, amount, self._budget_frequency_input.currentText()
            )
        except ValueError as exc:
            QMessageBox.information(self, "Couldn't add that cost", str(exc))
            return
        self._on_budget_clear()
        self._refresh_budget()

    def _on_budget_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            self._selected_budget_entry_id = None
            return
        entry_id = current.data(_USER_ROLE)
        project = self._services.active_project()
        if entry_id is None or project is None:
            return
        entry = next(
            (e for e in self._services.budget_tracker.list_entries(project.id) if e.id == entry_id),
            None,
        )
        if entry is None:
            return
        self._selected_budget_entry_id = entry.id
        self._budget_name_input.setText(entry.name)
        self._budget_amount_input.setText(str(entry.amount))
        self._budget_frequency_input.setCurrentText(entry.frequency)

    def _on_budget_clear(self) -> None:
        self._selected_budget_entry_id = None
        self._budget_list.setCurrentItem(None)
        self._budget_name_input.clear()
        self._budget_amount_input.clear()
        self._budget_frequency_input.setCurrentIndex(0)

    def _on_budget_save(self) -> None:
        if self._selected_budget_entry_id is None:
            return
        name = self._budget_name_input.text().strip()
        try:
            amount = float(self._budget_amount_input.text().strip() or "0")
        except ValueError:
            QMessageBox.information(self, "Not a number", "Enter the amount as a number.")
            return
        try:
            self._services.budget_tracker.update_entry(
                self._selected_budget_entry_id,
                name,
                amount,
                self._budget_frequency_input.currentText(),
            )
        except ValueError as exc:
            QMessageBox.information(self, "Couldn't save that cost", str(exc))
            return
        self._refresh_budget()

    def _on_budget_delete(self) -> None:
        if self._selected_budget_entry_id is None:
            return
        self._services.budget_tracker.delete_entry(self._selected_budget_entry_id)
        self._on_budget_clear()
        self._refresh_budget()

    def _refresh_budget(self) -> None:
        self._budget_list.blockSignals(True)
        self._budget_list.clear()
        project = self._services.active_project()
        if project is None:
            self._budget_list.blockSignals(False)
            self._funds_input.clear()
            self._runway_value.setText("—")
            self._runway_detail.setText(
                "Select a project on the Projects screen to track its budget and runway."
            )
            return
        self._funds_input.setText(str(self._services.budget_tracker.get_available_funds(project.id)))
        entries = self._services.budget_tracker.list_entries(project.id)
        for entry in entries:
            item = QListWidgetItem(f"{entry.name} — {entry.amount:g}/{entry.frequency}")
            item.setData(_USER_ROLE, entry.id)
            self._budget_list.addItem(item)
        self._budget_list.blockSignals(False)
        self._render_runway(self._services.budget_tracker.runway(project))

    def _render_runway(self, summary: RunwaySummary) -> None:
        if summary.entry_count == 0:
            self._runway_value.setText(f"{summary.available_funds:g}")
            self._runway_detail.setText(
                "Available funds. No recurring costs entered yet — add one above."
            )
            return
        if summary.is_indefinite:
            self._runway_value.setText("Indefinite")
            self._runway_detail.setText(
                f"Available funds: {summary.available_funds:g}. Monthly burn: "
                f"{summary.monthly_burn:g} (zero, from {summary.entry_count} recurring cost(s))."
            )
            return
        months = summary.runway_months or 0.0
        if summary.is_depleted:
            self._runway_value.setText("0 months")
            self._runway_detail.setText(
                f"Already at or past zero. Available funds: {summary.available_funds:g}. "
                f"Monthly burn: {summary.monthly_burn:g}."
            )
            return
        self._runway_value.setText(f"~{months:.1f} months")
        self._runway_detail.setText(
            f"Available funds: {summary.available_funds:g}. Monthly burn: "
            f"{summary.monthly_burn:g} (from {summary.entry_count} recurring cost(s))."
        )

    # --- Competitive Landscape Scan -------------------------------------------

    def _build_landscape_scan(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Competitive Landscape Scan")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Describe your game (genre, core mechanics, rough scope) and Spiced suggests "
            "comparable titles and general positioning thoughts, from the AI's general "
            "knowledge only — Spiced has no live connection to any storefront."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        notice = QLabel(
            "Approximate and potentially outdated — not live market data. Verify current "
            "pricing, review counts, and positioning yourself."
        )
        notice.setObjectName("Muted")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        self._landscape_input = QPlainTextEdit()
        self._landscape_input.setPlaceholderText(
            "e.g. A cozy 2D farming sim with light co-op, roughly 10-15 hours of content…"
        )
        self._landscape_input.setFixedHeight(100)
        layout.addWidget(self._landscape_input)

        row = QHBoxLayout()
        row.addStretch(1)
        self._landscape_scan_btn = PillButton("Scan landscape")
        self._landscape_scan_btn.clicked.connect(self._on_landscape_scan)
        row.addWidget(self._landscape_scan_btn)
        layout.addLayout(row)

        result_label = QLabel("Result")
        result_label.setObjectName("SectionTitle")
        layout.addWidget(result_label)
        self._landscape_result = QTextEdit()
        self._landscape_result.setReadOnly(True)
        self._landscape_result.setPlaceholderText("Your landscape scan will appear here.")
        self._landscape_result.setFixedHeight(200)
        layout.addWidget(self._landscape_result)

        history_title = QLabel("Recent scans")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._landscape_history = QTextEdit()
        self._landscape_history.setReadOnly(True)
        self._landscape_history.setFixedHeight(90)
        layout.addWidget(self._landscape_history)

    def _on_landscape_scan(self) -> None:
        description = self._landscape_input.toPlainText().strip()
        if not description:
            QMessageBox.information(
                self, "Nothing to scan", "Describe your game first (genre, mechanics, scope)."
            )
            return
        self._landscape_scan_btn.setEnabled(False)
        self._landscape_scan_btn.setText("Scanning…")
        self._landscape_result.clear()

        worker = _LandscapeWorker(self._services, description)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.chunk.connect(self._on_landscape_chunk)
        worker.done.connect(self._on_landscape_done)
        worker.failed.connect(self._on_landscape_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_landscape_chunk(self, text: str) -> None:
        _append_chunk(self._landscape_result, text)

    def _on_landscape_done(self, result: CompetitiveLandscapeResult) -> None:
        self._landscape_scan_btn.setEnabled(True)
        self._landscape_scan_btn.setText("Scan landscape")
        self._landscape_result.setPlainText(result.response_text)
        self.usage_changed.emit()
        self._refresh_landscape_history()

    def _on_landscape_failed(self, message: str) -> None:
        self._landscape_scan_btn.setEnabled(True)
        self._landscape_scan_btn.setText("Scan landscape")
        self._landscape_result.setPlainText(message)

    def _refresh_landscape_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._landscape_history.setPlainText(
                "Scans are saved once you select an active project."
            )
            return
        reports = self._services.competitive_landscape.history(project.id, limit=5)
        if not reports:
            self._landscape_history.setPlainText("No landscape scans saved for this project yet.")
            return
        lines = [f"[{r.created_at}] {(r.description_excerpt or '')[:80]}" for r in reports]
        self._landscape_history.setPlainText("\n".join(lines))

    # --- Refresh ---------------------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to "
                "track a budget and save landscape scans."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")
        self._refresh_budget()
        self._refresh_landscape_history()
        self._on_budget_clear()
