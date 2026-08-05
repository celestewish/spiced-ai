"""Marketing: Store Page Advisor, Wishlist/Analytics Summary, Screenshot Checklist.

Three sections, each following the established pattern: local/deterministic
work (CSV diffing, Pillow image checks) happens instantly with no AI
provider; AI review calls run the selected provider on a worker thread. The
Wishlist/Analytics Summary never sends anything to an AI provider at all —
its digest is a purely local diff. The Screenshot Checklist never sends raw
image bytes to any AI provider — only filenames, deterministic findings, and
developer-supplied captions.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
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
from spiced.core.store_page_advisor import ProviderNotReadyError as StorePageNotReadyError
from spiced.core.store_page_advisor import StorePageReviewResult
from spiced.core.trailer_screenshot_checklist import (
    ProviderNotReadyError as ScreenshotNotReadyError,
)
from spiced.core.trailer_screenshot_checklist import (
    ScreenshotChecklistFindings,
    ScreenshotChecklistResult,
    UnreadableImageError,
    scan_screenshots,
)
from spiced.core.wishlist_analytics import InvalidAnalyticsFormatError, WishlistAnalyticsDigest
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.source_link import SourceLinkExpander

ANALYTICS_FORMAT_NOTE = (
    "Wishlist/Analytics Summary works from an export you paste or import — Spiced does not "
    "connect live to Steam or itch (neither offers a public, OAuth-free wishlist/analytics API "
    "that this app could integrate against). Export your own numbers into this documented "
    "format, one metric per line:\n\n"
    "metric,value\nwishlists,1240\nconversion_pct,3.8\nvisits,15300\ntop_referrer,twitter\n\n"
    "Any subset of these (or extra metrics) works. Each import is diffed against your previous "
    "import for this project, entirely locally — no AI call, no network."
)


class _StorePageWorker(QObject):
    done = Signal(object)  # StorePageReviewResult
    failed = Signal(str)

    def __init__(self, services: Services, title: str, description: str, tags_text: str) -> None:
        super().__init__()
        self._services = services
        self._title = title
        self._description = description
        self._tags_text = tags_text

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            review = self._services.store_page_advisor.review(
                provider,
                self._title,
                self._description,
                self._tags_text,
                project=self._services.active_project(),
                record_usage=self._services.usage.record_prompt,
            )
            self._services.record_telemetry_event("marketing.store_page_review_run")
            self.done.emit(review)
        except StorePageNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during the review: {exc}")


class _ScreenshotChecklistWorker(QObject):
    done = Signal(object)  # ScreenshotChecklistResult
    failed = Signal(str)

    def __init__(
        self,
        services: Services,
        findings: ScreenshotChecklistFindings,
        captions: dict[str, str],
    ) -> None:
        super().__init__()
        self._services = services
        self._findings = findings
        self._captions = captions

    def run(self) -> None:
        try:
            provider = self._services.build_provider()
            result = self._services.screenshot_checklist.analyze(
                provider,
                self._findings,
                captions=self._captions,
                project=self._services.active_project(),
                record_usage=self._services.usage.record_prompt,
            )
            self._services.record_telemetry_event("marketing.screenshot_checklist_run")
            self.done.emit(result)
        except ScreenshotNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during the review: {exc}")


class MarketingScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._screenshot_paths: list[str] = []

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

        title = QLabel("Marketing")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        self._build_store_page_advisor(layout)
        self._build_wishlist_analytics(layout)
        self._build_screenshot_checklist(layout)

        self.refresh()

    # --- Store Page Optimization Advisor ------------------------------------

    def _build_store_page_advisor(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Store Page Optimization Advisor")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Paste or import your Steam/itch store page draft — title, description, tags. "
            "Spiced reviews it against a few commonly recommended practices (a clear first-line "
            "hook, readable tags, common mistakes) and gives specific suggestions. These are "
            "suggestions only, never a guarantee of sales — nothing here can know how a page "
            "will actually convert."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Title:"))
        self._sp_title_input = QLineEdit()
        self._sp_title_input.setPlaceholderText("Your game's store page title")
        title_row.addWidget(self._sp_title_input, 1)
        layout.addLayout(title_row)

        self._sp_description_input = QPlainTextEdit()
        self._sp_description_input.setPlaceholderText("Paste your store page description here…")
        self._sp_description_input.setFixedHeight(120)
        layout.addWidget(self._sp_description_input)

        tags_row = QHBoxLayout()
        tags_row.addWidget(QLabel("Tags:"))
        self._sp_tags_input = QLineEdit()
        self._sp_tags_input.setPlaceholderText("comma-separated, e.g. Roguelike, Pixel Art, Co-op")
        tags_row.addWidget(self._sp_tags_input, 1)
        layout.addLayout(tags_row)

        row = QHBoxLayout()
        self._sp_import_btn = QPushButton("Import draft file…")
        self._sp_import_btn.clicked.connect(self._on_sp_import)
        row.addWidget(self._sp_import_btn)
        row.addStretch(1)
        self._sp_review_btn = QPushButton("Review store page")
        self._sp_review_btn.clicked.connect(self._on_sp_review)
        row.addWidget(self._sp_review_btn)
        layout.addLayout(row)

        self._sp_result = QTextEdit()
        self._sp_result.setReadOnly(True)
        self._sp_result.setPlaceholderText("Your suggestions-only review will appear here.")
        self._sp_result.setFixedHeight(200)
        layout.addWidget(self._sp_result)

        self._sp_source_link = SourceLinkExpander()
        layout.addWidget(self._sp_source_link)

        history_title = QLabel("Recent reviews")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._sp_history = QTextEdit()
        self._sp_history.setReadOnly(True)
        self._sp_history.setFixedHeight(90)
        layout.addWidget(self._sp_history)

    def _on_sp_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a store page draft", "", "Text files (*.txt *.md);;All files (*)"
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
        self._sp_description_input.setPlainText(text)

    def _on_sp_review(self) -> None:
        title = self._sp_title_input.text().strip()
        description = self._sp_description_input.toPlainText().strip()
        if not title and not description:
            QMessageBox.information(
                self, "Nothing to review", "Enter at least a title or description first."
            )
            return
        self._sp_review_btn.setEnabled(False)
        self._sp_review_btn.setText("Reviewing…")
        self._sp_result.setPlainText("Reading your draft and thinking it through…")

        worker = _StorePageWorker(
            self._services, title, description, self._sp_tags_input.text()
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_sp_done)
        worker.failed.connect(self._on_sp_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_sp_done(self, result: StorePageReviewResult) -> None:
        self._sp_review_btn.setEnabled(True)
        self._sp_review_btn.setText("Review store page")
        self._sp_result.setPlainText(result.response_text)
        excerpt = f"Title: {result.draft.title}\n\n{result.draft.description}"
        self._sp_source_link.set_source(
            "From the title/description/tags you entered above (suggestions only).", excerpt
        )
        self.usage_changed.emit()
        self._refresh_sp_history()

    def _on_sp_failed(self, message: str) -> None:
        self._sp_review_btn.setEnabled(True)
        self._sp_review_btn.setText("Review store page")
        self._sp_result.setPlainText(message)
        self._sp_source_link.set_source(None, None)

    def _refresh_sp_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._sp_history.setPlainText("Reviews are saved once you select an active project.")
            return
        reviews = self._services.store_page_advisor.history(project.id, limit=5)
        if not reviews:
            self._sp_history.setPlainText("No store page reviews saved for this project yet.")
            return
        lines = [f"[{r.created_at}] {r.title or '(untitled)'}" for r in reviews]
        self._sp_history.setPlainText("\n".join(lines))

    # --- Wishlist/Analytics Summary ------------------------------------------

    def _build_wishlist_analytics(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Wishlist/Analytics Summary")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        note = QLabel(ANALYTICS_FORMAT_NOTE)
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._wa_input = QPlainTextEdit()
        self._wa_input.setPlaceholderText(
            "metric,value\nwishlists,1240\nconversion_pct,3.8\nvisits,15300\ntop_referrer,twitter"
        )
        self._wa_input.setFixedHeight(120)
        layout.addWidget(self._wa_input)

        row = QHBoxLayout()
        self._wa_import_btn = QPushButton("Import CSV file…")
        self._wa_import_btn.clicked.connect(self._on_wa_import)
        row.addWidget(self._wa_import_btn)
        row.addStretch(1)
        self._wa_digest_btn = QPushButton("Import & diff (local, free)")
        self._wa_digest_btn.clicked.connect(self._on_wa_digest)
        row.addWidget(self._wa_digest_btn)
        layout.addLayout(row)

        self._wa_result = QTextEdit()
        self._wa_result.setReadOnly(True)
        self._wa_result.setPlaceholderText(
            "Your weekly analytics digest (what's working, what's flat, what changed) will "
            "appear here."
        )
        self._wa_result.setFixedHeight(180)
        layout.addWidget(self._wa_result)

        history_title = QLabel("Recent imports")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._wa_history = QTextEdit()
        self._wa_history.setReadOnly(True)
        self._wa_history.setFixedHeight(90)
        layout.addWidget(self._wa_history)

    def _on_wa_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import an analytics export", "", "CSV files (*.csv);;All files (*)"
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
        self._wa_input.setPlainText(text)
        self._on_wa_digest(source_filename=Path(path).name)

    def _on_wa_digest(self, source_filename: str | None = None) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        text = self._wa_input.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Nothing to import", "Paste or import analytics CSV first."
            )
            return
        try:
            digest = self._services.wishlist_analytics.import_csv(
                project, text, source_filename=source_filename
            )
        except InvalidAnalyticsFormatError as exc:
            QMessageBox.warning(self, "Couldn't read that format", str(exc))
            return
        self._services.record_telemetry_event("marketing.wishlist_analytics_import_run")
        self._render_wa_digest(digest)
        self._refresh_wa_history()

    def _render_wa_digest(self, digest: WishlistAnalyticsDigest) -> None:
        lines = ["Weekly analytics digest (local diff, no AI used):", ""]
        lines.extend(f"- {line}" for line in digest.summary_lines)
        lines.append("")
        lines.append("Current values:")
        for metric, value in digest.metrics.items():
            lines.append(f"- {metric}: {value}")
        self._wa_result.setPlainText("\n".join(lines))

    def _refresh_wa_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._wa_history.setPlainText("Imports are saved once you select an active project.")
            return
        imports = self._services.wishlist_analytics.history(project.id, limit=5)
        if not imports:
            self._wa_history.setPlainText("No analytics imports saved for this project yet.")
            return
        lines = []
        for imp in imports:
            top = ", ".join(f"{k}={v}" for k, v in list(imp.metrics.items())[:3])
            lines.append(f"[{imp.created_at}] {top}")
        self._wa_history.setPlainText("\n".join(lines))

    # --- Trailer & Screenshot Checklist ---------------------------------------

    def _build_screenshot_checklist(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Trailer & Screenshot Checklist")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Screenshots only — a video trailer needs frame-by-frame content understanding "
            "Spiced has no tooling for here, so deep trailer analysis is out of scope. Upload "
            "screenshot files below: Spiced runs local, deterministic checks (resolution/aspect "
            "ratio against common store sizes, and a heuristic that flags likely-blank/loading-"
            "screen shots for your own review), then an AI pass reviews the set — but only "
            "filenames, those deterministic findings, and any caption text you add per shot. "
            "Raw image bytes are never sent to the AI provider."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._sc_upload_btn = QPushButton("Upload screenshots…")
        self._sc_upload_btn.clicked.connect(self._on_sc_upload)
        row.addWidget(self._sc_upload_btn)
        row.addStretch(1)
        self._sc_clear_btn = QPushButton("Clear")
        self._sc_clear_btn.setObjectName("Ghost")
        self._sc_clear_btn.clicked.connect(self._on_sc_clear)
        row.addWidget(self._sc_clear_btn)
        layout.addLayout(row)

        self._sc_list = QListWidget()
        self._sc_list.setFixedHeight(100)
        layout.addWidget(self._sc_list)

        caption_row = QHBoxLayout()
        caption_row.addWidget(QLabel("Caption for selected shot (optional):"))
        self._sc_caption_input = QLineEdit()
        self._sc_caption_input.setPlaceholderText(
            "e.g. \"Mid-game boss fight in the ice caverns\""
        )
        self._sc_caption_input.editingFinished.connect(self._on_sc_caption_edited)
        caption_row.addWidget(self._sc_caption_input, 1)
        layout.addLayout(caption_row)
        self._sc_list.currentItemChanged.connect(self._on_sc_item_selected)
        self._sc_captions: dict[str, str] = {}

        review_row = QHBoxLayout()
        review_row.addStretch(1)
        self._sc_review_btn = QPushButton("Run checklist")
        self._sc_review_btn.clicked.connect(self._on_sc_review)
        review_row.addWidget(self._sc_review_btn)
        layout.addLayout(review_row)

        self._sc_result = QTextEdit()
        self._sc_result.setReadOnly(True)
        self._sc_result.setPlaceholderText(
            "Deterministic per-image findings and the AI's set review will appear here."
        )
        self._sc_result.setFixedHeight(220)
        layout.addWidget(self._sc_result)

        history_title = QLabel("Recent checklist runs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._sc_history = QTextEdit()
        self._sc_history.setReadOnly(True)
        self._sc_history.setFixedHeight(90)
        layout.addWidget(self._sc_history)

    def _on_sc_upload(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Upload screenshots",
            "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)",
        )
        if not paths:
            return
        self._screenshot_paths.extend(paths)
        self._refresh_sc_list()

    def _on_sc_clear(self) -> None:
        self._screenshot_paths = []
        self._sc_captions = {}
        self._refresh_sc_list()

    def _refresh_sc_list(self) -> None:
        self._sc_list.clear()
        for path in self._screenshot_paths:
            self._sc_list.addItem(QListWidgetItem(Path(path).name))

    def _on_sc_item_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            self._sc_caption_input.clear()
            return
        self._sc_caption_input.setText(self._sc_captions.get(current.text(), ""))

    def _on_sc_caption_edited(self) -> None:
        current = self._sc_list.currentItem()
        if current is None:
            return
        text = self._sc_caption_input.text().strip()
        if text:
            self._sc_captions[current.text()] = text
        else:
            self._sc_captions.pop(current.text(), None)

    def _on_sc_review(self) -> None:
        if not self._screenshot_paths:
            QMessageBox.information(
                self, "Nothing to check", "Upload one or more screenshots first."
            )
            return
        try:
            findings = scan_screenshots(self._screenshot_paths)
        except UnreadableImageError as exc:
            QMessageBox.warning(self, "Couldn't read an image", str(exc))
            return

        self._sc_review_btn.setEnabled(False)
        self._sc_review_btn.setText("Checking…")
        self._sc_result.setPlainText(_format_screenshot_findings_local(findings))

        worker = _ScreenshotChecklistWorker(self._services, findings, dict(self._sc_captions))
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_sc_done)
        worker.failed.connect(self._on_sc_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_sc_done(self, result: ScreenshotChecklistResult) -> None:
        self._sc_review_btn.setEnabled(True)
        self._sc_review_btn.setText("Run checklist")
        text = _format_screenshot_findings_local(result.findings)
        text += f"\n\n--- AI review of the set ---\n{result.response_text}"
        self._sc_result.setPlainText(text)
        self.usage_changed.emit()
        self._refresh_sc_history()

    def _on_sc_failed(self, message: str) -> None:
        self._sc_review_btn.setEnabled(True)
        self._sc_review_btn.setText("Run checklist")
        self._sc_result.setPlainText(message)

    def _refresh_sc_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._sc_history.setPlainText("Runs are saved once you select an active project.")
            return
        reports = self._services.screenshot_checklist.history(project.id, limit=5)
        if not reports:
            self._sc_history.setPlainText("No screenshot checklist runs saved yet.")
            return
        lines = [f"[{r.created_at}] {len(r.findings)} screenshot(s) reviewed" for r in reports]
        self._sc_history.setPlainText("\n".join(lines))

    # --- Refresh ---------------------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to "
                "save reviews, analytics imports, and checklist runs."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")
        self._refresh_sp_history()
        self._refresh_wa_history()
        self._refresh_sc_history()


def _format_screenshot_findings_local(findings: ScreenshotChecklistFindings) -> str:
    lines = ["Local scan (no AI used):"]
    if not findings.findings:
        lines.append("No screenshots scanned.")
        return "\n".join(lines)
    for f in findings.findings:
        flags = []
        if not f.meets_min_resolution:
            flags.append("below minimum resolution")
        elif not f.meets_recommended_resolution:
            flags.append("below recommended resolution")
        if not f.aspect_ratio_ok:
            flags.append("unusual aspect ratio")
        if f.likely_blank:
            flags.append("likely blank/low-variance")
        flag_text = ", ".join(flags) if flags else "no technical flags"
        lines.append(f"- {f.filename}: {f.width}x{f.height} ({flag_text})")
    lines.append(f"\n{findings.flagged_count} of {len(findings.findings)} flagged for a look.")
    return "\n".join(lines)
