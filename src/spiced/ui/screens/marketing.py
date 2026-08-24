"""Marketing: Store Page Advisor and Wishlist/Analytics Summary.

Both sections follow the established pattern: local/deterministic work (CSV
diffing) happens instantly with no AI provider; the Store Page Advisor's
review call runs the selected provider on a worker thread. The Wishlist/
Analytics Summary never sends anything to an AI provider at all — its digest
is a purely local diff.

The Trailer & Screenshot Checklist previously lived here too; it's been
removed (product decision — a checklist that can only compare pixel
dimensions and flag near-blank frames doesn't carry its weight as a
dedicated tool). The underlying scan/review service (core.trailer_
screenshot_checklist) is untouched in case it resurfaces elsewhere.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.store_page_advisor import ProviderNotReadyError as StorePageNotReadyError
from spiced.core.store_page_advisor import StorePageReviewResult
from spiced.core.wishlist_analytics import InvalidAnalyticsFormatError, WishlistAnalyticsDigest
from spiced.ui.thread_utils import AIStreamWorker, launch_worker
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.source_link import SourceLinkExpander

ANALYTICS_FORMAT_NOTE = (
    "Works from an export you paste or import — Spiced doesn't connect live to Steam or itch "
    "(neither offers a public API for this). One metric per line:\n\n"
    "metric,value\nwishlists,1240\nconversion_pct,3.8\nvisits,15300\ntop_referrer,twitter\n\n"
    "Any subset (or extra metrics) works. Diffed against your previous import, locally — no AI, "
    "no network."
)

# Stat tiles pulled out of the digest, in display order — see
# _render_wa_tiles. Any metric not in this list (or missing from the
# import) just doesn't get a tile; the full digest text below still shows it.
_TILE_METRICS = [
    ("wishlists", "Wishlists"),
    ("conversion_pct", "Conversion %"),
    ("top_referrer", "Top Referrer"),
]


def _append_chunk(widget: QTextEdit, text: str) -> None:
    """Append streamed text to a result widget in place -- see the
    equivalent helper in ui.screens.debugging for the full rationale."""
    cursor = widget.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText(text)
    widget.setTextCursor(cursor)


class _StorePageWorker(AIStreamWorker):
    def __init__(self, services: Services, title: str, description: str, tags_text: str) -> None:
        super().__init__()
        self._services = services
        self._title = title
        self._description = description
        self._tags_text = tags_text

    def _call(self, on_chunk):
        provider = self._services.build_provider()
        review = self._services.store_page_advisor.review(
            provider,
            self._title,
            self._description,
            self._tags_text,
            project=self._services.active_project(),
            record_usage=self._services.usage.record_prompt,
            on_chunk=on_chunk,
        )
        self._services.record_telemetry_event("marketing.store_page_review_run")
        return review

    def expected_errors(self):
        return (StorePageNotReadyError,)

    def error_message(self, exc: Exception) -> str:
        return f"Something went wrong during the review: {exc}"


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


class MarketingScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services

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

        title = QLabel("Marketing")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        hero = QFrame()
        hero.setObjectName("ToolHeroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        hero_layout.setSpacing(10)
        self._build_store_page_advisor(hero_layout)
        layout.addWidget(hero)

        analytics_card = _card()
        self._build_wishlist_analytics(analytics_card.layout())
        layout.addWidget(analytics_card)

        self.refresh()

    # --- Store Page Optimization Advisor ------------------------------------

    def _build_store_page_advisor(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Store Page Optimization Advisor")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Paste your Steam/itch store page draft. Spiced checks it against a few common best "
            "practices — a clear opening hook, readable tags — and suggests specific tweaks. "
            "It's a second pair of eyes, not a guarantee of sales."
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
        self._sp_import_btn = PillButton("Import draft file…", ghost=True)
        self._sp_import_btn.clicked.connect(self._on_sp_import)
        row.addWidget(self._sp_import_btn)
        row.addStretch(1)
        self._sp_review_btn = PillButton("Review store page", water_fill=True)
        self._sp_review_btn.clicked.connect(self._on_sp_review)
        row.addWidget(self._sp_review_btn)
        layout.addLayout(row)

        result_label = QLabel("Result")
        result_label.setObjectName("SectionTitle")
        layout.addWidget(result_label)
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
        self._sp_review_btn.set_loading(True)
        self._sp_result.clear()

        worker = _StorePageWorker(
            self._services, title, description, self._sp_tags_input.text()
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.chunk.connect(self._on_sp_chunk)
        worker.done.connect(self._on_sp_done)
        worker.failed.connect(self._on_sp_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_sp_chunk(self, text: str) -> None:
        _append_chunk(self._sp_result, text)

    def _on_sp_done(self, result: StorePageReviewResult) -> None:
        self._sp_review_btn.setEnabled(True)
        self._sp_review_btn.setText("Review store page")
        self._sp_review_btn.set_loading(False)
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
        self._sp_review_btn.set_loading(False)
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
        heading.setObjectName("CardTitle")
        heading.setToolTip(ANALYTICS_FORMAT_NOTE)
        layout.addWidget(heading)

        note = QLabel("Paste or import a wishlist/analytics export to see what's changed.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        # Stat tiles: the metrics a dev opens this card to see, pulled out
        # of the digest into the Dashboard's stat-card look instead of
        # buried in a text dump. Hidden until a digest exists.
        self._wa_tiles_row = QHBoxLayout()
        self._wa_tiles_row.setSpacing(14)
        self._wa_tile_widgets: dict[str, tuple[QFrame, QLabel]] = {}
        for key, label in _TILE_METRICS:
            tile = _card()
            tile_layout = tile.layout()
            tile_label = QLabel(label)
            tile_label.setObjectName("StatLabel")
            tile_layout.addWidget(tile_label)
            tile_value = QLabel("—")
            tile_value.setObjectName("StatValue")
            tile_layout.addWidget(tile_value)
            tile.setVisible(False)
            self._wa_tile_widgets[key] = (tile, tile_value)
            self._wa_tiles_row.addWidget(tile, 1)
        layout.addLayout(self._wa_tiles_row)

        self._wa_input = QPlainTextEdit()
        self._wa_input.setPlaceholderText(
            "metric,value\nwishlists,1240\nconversion_pct,3.8\nvisits,15300\ntop_referrer,twitter"
        )
        self._wa_input.setFixedHeight(100)
        layout.addWidget(self._wa_input)

        row = QHBoxLayout()
        self._wa_import_btn = PillButton("Import CSV file…", ghost=True)
        self._wa_import_btn.clicked.connect(self._on_wa_import)
        row.addWidget(self._wa_import_btn)
        row.addStretch(1)
        self._wa_digest_btn = PillButton("Import & diff")
        self._wa_digest_btn.clicked.connect(self._on_wa_digest)
        row.addWidget(self._wa_digest_btn)
        layout.addLayout(row)

        self._wa_result = QTextEdit()
        self._wa_result.setReadOnly(True)
        self._wa_result.setPlaceholderText(
            "Your weekly analytics digest (what's working, what's flat, what changed) will "
            "appear here."
        )
        self._wa_result.setFixedHeight(160)
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
        for key, (tile, value_label) in self._wa_tile_widgets.items():
            metric_value = digest.metrics.get(key)
            tile.setVisible(metric_value is not None)
            if metric_value is not None:
                value_label.setText(str(metric_value))

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

    # --- Refresh ---------------------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to "
                "save reviews and analytics imports."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")
        self._refresh_sp_history()
        self._refresh_wa_history()
