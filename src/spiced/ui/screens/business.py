"""Business: Contract/License Checklist, Budget/Runway Tracker, Grant/Funding
Finder, and Competitive Landscape Scan (Phase H, section 7 part 2).

Four sections, following the established pattern: local/deterministic work
(the runway arithmetic, the static grant dataset filter) works instantly
with no AI provider; the two AI-assisted sections (Contract Checklist,
Competitive Landscape Scan) run the selected provider on a worker thread.
The Contract Checklist is explicitly, repeatedly not legal advice — that
caveat appears in this screen's copy as well as in the prompt itself. The
Competitive Landscape Scan is explicitly labeled approximate/not live market
data, same discipline as the Grant Finder's "verify independently" caveat.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
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
from spiced.core.budget_tracker import RunwaySummary
from spiced.core.competitive_landscape import CompetitiveLandscapeResult
from spiced.core.competitive_landscape import ProviderNotReadyError as LandscapeNotReadyError
from spiced.core.contract_checklist import NOT_LEGAL_ADVICE_NOTICE, ContractChecklistResult
from spiced.core.contract_checklist import ProviderNotReadyError as ContractNotReadyError
from spiced.core.grant_finder import INFORMATIONAL_ONLY_NOTICE, find_grants
from spiced.storage.budget_entries import FREQUENCIES
from spiced.ui.thread_utils import launch_worker

_USER_ROLE = 0x0100


class _ContractChecklistWorker(QObject):
    done = Signal(object)  # ContractChecklistResult
    failed = Signal(str)

    def __init__(self, services: Services, text: str, source_filename: str | None) -> None:
        super().__init__()
        self._services = services
        self._text = text
        self._source_filename = source_filename

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            result = self._services.contract_checklist.review(
                provider,
                self._text,
                project=self._services.active_project(),
                source_filename=self._source_filename,
                record_usage=self._services.usage.record_prompt,
            )
            self._services.record_telemetry_event("business.contract_checklist_run")
            self.done.emit(result)
        except ContractNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during the review: {exc}")


class _LandscapeWorker(QObject):
    done = Signal(object)  # CompetitiveLandscapeResult
    failed = Signal(str)

    def __init__(self, services: Services, description: str) -> None:
        super().__init__()
        self._services = services
        self._description = description

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            result = self._services.competitive_landscape.analyze(
                provider,
                self._description,
                project=self._services.active_project(),
                record_usage=self._services.usage.record_prompt,
            )
            self._services.record_telemetry_event("business.competitive_landscape_run")
            self.done.emit(result)
        except LandscapeNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during the scan: {exc}")


class BusinessScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._contract_pending_filename: str | None = None
        self._selected_budget_entry_id: int | None = None

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

        title = QLabel("Business")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        self._build_contract_checklist(layout)
        self._build_budget_tracker(layout)
        self._build_grant_finder(layout)
        self._build_landscape_scan(layout)

        self.refresh()

    # --- Contract/License Checklist -----------------------------------------

    def _build_contract_checklist(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Contract/License Checklist")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Not legal advice. Paste or import a contract/license document (plain text or "
            "Markdown — this feature does not parse .docx, since a legal document deserves "
            "less new file-handling surface than a design doc; copy the text out and paste it "
            "here instead). Spiced points out common gaps and red flags worth asking a real "
            "lawyer about. It is never a verdict on whether something is safe, fair, or "
            "enforceable — always have a real lawyer review anything that actually matters "
            "before you sign."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        notice = QLabel(NOT_LEGAL_ADVICE_NOTICE)
        notice.setObjectName("Muted")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        self._contract_input = QPlainTextEdit()
        self._contract_input.setPlaceholderText("Paste your contract or license text here…")
        self._contract_input.setFixedHeight(140)
        layout.addWidget(self._contract_input)

        row = QHBoxLayout()
        self._contract_import_btn = QPushButton("Import file…")
        self._contract_import_btn.clicked.connect(self._on_contract_import)
        row.addWidget(self._contract_import_btn)
        row.addStretch(1)
        self._contract_review_btn = QPushButton("Get things to double check")
        self._contract_review_btn.clicked.connect(self._on_contract_review)
        row.addWidget(self._contract_review_btn)
        layout.addLayout(row)

        self._contract_result = QTextEdit()
        self._contract_result.setReadOnly(True)
        self._contract_result.setPlaceholderText(
            "A non-lawyer's \"things to double check\" list will appear here — not legal advice."
        )
        self._contract_result.setFixedHeight(200)
        layout.addWidget(self._contract_result)

        history_title = QLabel("Recent reviews")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._contract_history = QTextEdit()
        self._contract_history.setReadOnly(True)
        self._contract_history.setFixedHeight(90)
        layout.addWidget(self._contract_history)

    def _on_contract_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a contract or license", "", "Text files (*.txt *.md);;All files (*)"
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
        self._contract_input.setPlainText(text)
        self._contract_pending_filename = Path(path).name

    def _on_contract_review(self) -> None:
        text = self._contract_input.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Nothing to review", "Paste or import a document first."
            )
            return
        filename = self._contract_pending_filename
        self._contract_review_btn.setEnabled(False)
        self._contract_review_btn.setText("Reviewing…")
        self._contract_result.setPlainText("Reading the document and thinking it through…")

        worker = _ContractChecklistWorker(self._services, text, filename)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_contract_done)
        worker.failed.connect(self._on_contract_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_contract_done(self, result: ContractChecklistResult) -> None:
        self._contract_review_btn.setEnabled(True)
        self._contract_review_btn.setText("Get things to double check")
        self._contract_result.setPlainText(result.response_text)
        self._contract_pending_filename = None
        self.usage_changed.emit()
        self._refresh_contract_history()

    def _on_contract_failed(self, message: str) -> None:
        self._contract_review_btn.setEnabled(True)
        self._contract_review_btn.setText("Get things to double check")
        self._contract_result.setPlainText(message)

    def _refresh_contract_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._contract_history.setPlainText(
                "Reviews are saved once you select an active project."
            )
            return
        reviews = self._services.contract_checklist.history(project.id, limit=5)
        if not reviews:
            self._contract_history.setPlainText("No contract checklist reviews saved yet.")
            return
        lines = [
            f"[{r.created_at}] {r.source_filename or '(pasted text)'}" for r in reviews
        ]
        self._contract_history.setPlainText("\n".join(lines))

    # --- Budget/Runway Tracker ----------------------------------------------

    def _build_budget_tracker(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Budget/Runway Tracker")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Your own offline expense tracking — not Spiced's billing (Spiced has none). Enter "
            "your recurring costs and available funds; Spiced computes an estimated runway in "
            "plain terms. Purely local arithmetic — works with no AI provider configured."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        funds_row = QHBoxLayout()
        funds_row.addWidget(QLabel("Funds available:"))
        self._funds_input = QLineEdit()
        self._funds_input.setPlaceholderText("e.g. 5000")
        funds_row.addWidget(self._funds_input, 1)
        self._funds_save_btn = QPushButton("Save")
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
        self._budget_frequency_input = QComboBox()
        self._budget_frequency_input.addItems(list(FREQUENCIES))
        form_row.addWidget(self._budget_frequency_input, 1)
        layout.addLayout(form_row)

        btn_row = QHBoxLayout()
        self._budget_clear_btn = QPushButton("New / clear")
        self._budget_clear_btn.clicked.connect(self._on_budget_clear)
        btn_row.addWidget(self._budget_clear_btn)
        self._budget_delete_btn = QPushButton("Delete")
        self._budget_delete_btn.clicked.connect(self._on_budget_delete)
        btn_row.addWidget(self._budget_delete_btn)
        btn_row.addStretch(1)
        self._budget_add_btn = QPushButton("Add cost")
        self._budget_add_btn.clicked.connect(self._on_budget_add)
        btn_row.addWidget(self._budget_add_btn)
        self._budget_save_btn = QPushButton("Save changes")
        self._budget_save_btn.clicked.connect(self._on_budget_save)
        btn_row.addWidget(self._budget_save_btn)
        layout.addLayout(btn_row)

        self._budget_list = QListWidget()
        self._budget_list.setFixedHeight(120)
        self._budget_list.currentItemChanged.connect(self._on_budget_selected)
        layout.addWidget(self._budget_list)

        self._runway_summary = QLabel()
        self._runway_summary.setObjectName("Muted")
        self._runway_summary.setWordWrap(True)
        layout.addWidget(self._runway_summary)

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
            self._runway_summary.setText(
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
            self._runway_summary.setText(
                f"Available funds: {summary.available_funds:g}. No recurring costs entered yet "
                "— add one above to estimate a runway."
            )
            return
        if summary.is_indefinite:
            self._runway_summary.setText(
                f"Available funds: {summary.available_funds:g}. Monthly burn: "
                f"{summary.monthly_burn:g}. Runway: indefinite at a monthly burn of 0."
            )
            return
        months = summary.runway_months or 0.0
        status = "already at or past zero" if summary.is_depleted else f"about {months:.1f} months"
        self._runway_summary.setText(
            f"Available funds: {summary.available_funds:g}. Monthly burn: "
            f"{summary.monthly_burn:g} (from {summary.entry_count} recurring cost(s)). "
            f"Estimated runway: {status}."
        )

    # --- Grant/Funding Finder ------------------------------------------------

    def _build_grant_finder(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Grant/Funding Finder")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "A small, curated list of well-known, long-established funding programs — general, "
            "slow-changing facts, not precise current amounts or deadlines Spiced can't verify "
            "stay accurate."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        notice = QLabel(INFORMATIONAL_ONLY_NOTICE)
        notice.setObjectName("Muted")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        filter_row = QHBoxLayout()
        self._grant_project_type_input = QLineEdit()
        self._grant_project_type_input.setPlaceholderText("Engine/project type (e.g. Unreal)")
        filter_row.addWidget(self._grant_project_type_input, 1)
        self._grant_region_input = QLineEdit()
        self._grant_region_input.setPlaceholderText("Region (e.g. UK)")
        filter_row.addWidget(self._grant_region_input, 1)
        self._grant_stage_input = QLineEdit()
        self._grant_stage_input.setPlaceholderText("Stage (e.g. seed)")
        filter_row.addWidget(self._grant_stage_input, 1)
        self._grant_search_btn = QPushButton("Search")
        self._grant_search_btn.clicked.connect(self._on_grant_search)
        filter_row.addWidget(self._grant_search_btn)
        layout.addLayout(filter_row)

        self._grant_result = QTextEdit()
        self._grant_result.setReadOnly(True)
        self._grant_result.setFixedHeight(180)
        layout.addWidget(self._grant_result)

        self._on_grant_search()

    def _on_grant_search(self) -> None:
        grants = find_grants(
            project_type=self._grant_project_type_input.text().strip(),
            region=self._grant_region_input.text().strip(),
            stage=self._grant_stage_input.text().strip(),
        )
        if not grants:
            self._grant_result.setPlainText(
                "No entries in Spiced's small curated list matched those filters. Try clearing "
                "a filter — most entries are broadly applicable."
            )
            return
        lines = []
        for g in grants:
            lines.append(f"{g.name} — {g.url}")
            lines.append(g.description)
            lines.append(g.verify_note)
            lines.append("")
        self._grant_result.setPlainText("\n".join(lines).strip())

    # --- Competitive Landscape Scan -------------------------------------------

    def _build_landscape_scan(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Competitive Landscape Scan")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Describe your game (genre, core mechanics, rough scope) and Spiced suggests "
            "comparable existing titles and general positioning thoughts — framed to inform, "
            "never to discourage. This works from the AI's general knowledge only; Spiced has "
            "no live connection to Steam, itch, or any storefront."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        notice = QLabel(
            "Approximate and potentially outdated — not live market data. Verify current "
            "pricing, review counts, and positioning yourself before drawing conclusions."
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
        self._landscape_scan_btn = QPushButton("Scan landscape")
        self._landscape_scan_btn.clicked.connect(self._on_landscape_scan)
        row.addWidget(self._landscape_scan_btn)
        layout.addLayout(row)

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
        self._landscape_result.setPlainText("Thinking through comparable titles…")

        worker = _LandscapeWorker(self._services, description)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_landscape_done)
        worker.failed.connect(self._on_landscape_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

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
                "save reviews, track a budget, and save landscape scans."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")
        self._refresh_contract_history()
        self._refresh_budget()
        self._refresh_landscape_history()
        self._on_budget_clear()
