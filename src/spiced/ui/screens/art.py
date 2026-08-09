"""Art: Asset Review Queue, Style Consistency Checker, In-Engine Placement Preview.

Three sections, all local/deterministic -- no AI provider is used anywhere
on this screen. Recursive folder scans still run on a worker thread (via
``ui.thread_utils.launch_worker``) purely for UI responsiveness, the same
pattern the Asset Optimization Sweep and Localization Readiness scans use
even though they, too, involve no AI call.
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
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.asset_review_queue import (
    REVIEW_QUEUE_CAVEAT,
    AssetReviewResult,
    UnreadableAssetError,
    iter_folder_files,
)
from spiced.core.placement_preview import (
    PLACEMENT_PREVIEW_DISCLAIMER,
    PlacementPreviewResult,
    create_placement_preview,
)
from spiced.core.placement_preview import (
    UnreadableImageError as PlacementUnreadableImageError,
)
from spiced.core.style_consistency import (
    STYLE_CONSISTENCY_CAVEAT,
    StyleConsistencyResult,
    scan_population_for_outliers,
)
from spiced.core.style_consistency import (
    UnreadableImageError as StyleUnreadableImageError,
)
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.tool_switcher import build_tool_switcher


class _AssetReviewWorker(QObject):
    done = Signal(object)  # AssetReviewResult
    failed = Signal(str)

    def __init__(self, services: Services, paths: list[str]) -> None:
        super().__init__()
        self._services = services
        self._paths = paths

    def run(self) -> None:
        try:
            result = self._services.asset_review_queue.review(
                self._paths, project=self._services.active_project()
            )
            self._services.record_telemetry_event("art.asset_review_run")
            self.done.emit(result)
        except UnreadableAssetError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while reviewing assets: {exc}")


class _StyleConsistencyWorker(QObject):
    done = Signal(object)  # StyleConsistencyResult
    failed = Signal(str)

    def __init__(self, services: Services, paths: list[str]) -> None:
        super().__init__()
        self._services = services
        self._paths = paths

    def run(self) -> None:
        try:
            result = scan_population_for_outliers(self._paths)
            self._services.record_telemetry_event("art.style_consistency_run")
            self.done.emit(result)
        except StyleUnreadableImageError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during the style check: {exc}")


def _format_review_findings(result: AssetReviewResult) -> str:
    lines = [REVIEW_QUEUE_CAVEAT, ""]
    if not result.findings:
        lines.append("No assets reviewed.")
        return "\n".join(lines)
    for f in result.findings:
        status = "PASS" if f.passed else "FLAGGED"
        lines.append(f"[{status}] {Path(f.path).name}")
        for issue in f.issues:
            lines.append(f"    - {issue}")
    lines.append("")
    lines.append(f"{result.flagged_count} of {len(result.findings)} flagged for a look.")
    return "\n".join(lines)


def _format_style_result(result: StyleConsistencyResult) -> str:
    lines = [STYLE_CONSISTENCY_CAVEAT, ""]
    lines.append(f"Population size: {result.population_size} image(s).")
    if not result.outliers:
        lines.append("No clear statistical outliers found.")
        return "\n".join(lines)
    lines.append("")
    lines.append("Possible outliers:")
    for outlier in result.outliers:
        lines.append(f"- {Path(outlier.path).name}")
        for reason in outlier.reasons:
            lines.append(f"    - {reason}")
    return "\n".join(lines)


class ArtScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._review_paths: list[str] = []
        self._placement_background: str | None = None
        self._placement_asset: str | None = None

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

        title = QLabel("Art")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        columns, self._stack, self._tool_group = build_tool_switcher(
            self,
            [
                ("Asset Review Queue", self._build_review_queue),
                ("Style Consistency", self._build_style_consistency),
                ("Placement Preview", self._build_placement_preview),
            ],
        )
        layout.addLayout(columns, 1)

        self.refresh()

    # --- Asset Review Queue -------------------------------------------------

    def _build_review_queue(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Asset Review Queue")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Pick files, or paste a folder path, to review. Spiced runs local, deterministic "
            "checks: power-of-two resolution (a heads-up, not a hard rule), file-size sanity, "
            "source-only format warnings, and (for assets under this project's Assets/ folder) "
            ".meta introspection -- mipmap setting and a missing-.meta flag. Automated technical "
            "checks only, never an art-direction review."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._review_pick_btn = PillButton("Pick files…")
        self._review_pick_btn.clicked.connect(self._on_review_pick_files)
        row.addWidget(self._review_pick_btn)
        self._review_folder_input = QLineEdit()
        self._review_folder_input.setPlaceholderText("...or paste a folder path")
        row.addWidget(self._review_folder_input, 1)
        self._review_folder_btn = PillButton("Browse…")
        self._review_folder_btn.clicked.connect(self._on_review_browse_folder)
        row.addWidget(self._review_folder_btn)
        layout.addLayout(row)

        self._review_list = QListWidget()
        self._review_list.setFixedHeight(90)
        layout.addWidget(self._review_list)

        action_row = QHBoxLayout()
        self._review_clear_btn = PillButton("Clear", ghost=True)
        self._review_clear_btn.clicked.connect(self._on_review_clear)
        action_row.addWidget(self._review_clear_btn)
        action_row.addStretch(1)
        self._review_run_btn = PillButton("Review assets")
        self._review_run_btn.clicked.connect(self._on_review_run)
        action_row.addWidget(self._review_run_btn)
        layout.addLayout(action_row)

        self._review_result = QTextEdit()
        self._review_result.setReadOnly(True)
        self._review_result.setPlaceholderText("Per-asset pass/flag results will appear here.")
        self._review_result.setFixedHeight(220)
        layout.addWidget(self._review_result)

        history_title = QLabel("Recent review runs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._review_history = QTextEdit()
        self._review_history.setReadOnly(True)
        self._review_history.setFixedHeight(80)
        layout.addWidget(self._review_history)

    def _on_review_pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Pick assets to review")
        if not paths:
            return
        self._review_paths.extend(p for p in paths if p not in self._review_paths)
        self._refresh_review_list()

    def _on_review_browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick a folder to review")
        if folder:
            self._review_folder_input.setText(folder)

    def _on_review_clear(self) -> None:
        self._review_paths = []
        self._review_folder_input.clear()
        self._refresh_review_list()

    def _refresh_review_list(self) -> None:
        self._review_list.clear()
        for path in self._review_paths:
            self._review_list.addItem(QListWidgetItem(Path(path).name))

    def _collect_review_paths(self) -> list[str]:
        paths = list(self._review_paths)
        folder = self._review_folder_input.text().strip()
        if folder:
            if Path(folder).is_dir():
                paths.extend(str(p) for p in iter_folder_files(folder))
            else:
                QMessageBox.information(self, "Folder not found", f'"{folder}" is not a folder.')
        return paths

    def _on_review_run(self) -> None:
        paths = self._collect_review_paths()
        if not paths:
            QMessageBox.information(
                self, "Nothing to review", "Pick files or enter a folder path first."
            )
            return
        self._review_run_btn.setEnabled(False)
        self._review_run_btn.setText("Reviewing…")
        self._review_result.setPlainText("Reviewing assets…")

        worker = _AssetReviewWorker(self._services, paths)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_review_done)
        worker.failed.connect(self._on_review_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_review_done(self, result: AssetReviewResult) -> None:
        self._review_run_btn.setEnabled(True)
        self._review_run_btn.setText("Review assets")
        self._review_result.setPlainText(_format_review_findings(result))
        self.usage_changed.emit()
        self._refresh_review_history()

    def _on_review_failed(self, message: str) -> None:
        self._review_run_btn.setEnabled(True)
        self._review_run_btn.setText("Review assets")
        self._review_result.setPlainText(message)

    def _refresh_review_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._review_history.setPlainText("Runs are saved once you select an active project.")
            return
        reports = self._services.asset_review_queue.history(project.id, limit=5)
        if not reports:
            self._review_history.setPlainText("No asset review runs saved yet.")
            return
        lines = [f"[{r.created_at}] {len(r.findings)} asset(s) reviewed" for r in reports]
        self._review_history.setPlainText("\n".join(lines))

    # --- Style Consistency Checker ------------------------------------------

    def _build_style_consistency(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Style Check")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Runs against the same files picked/loaded above for the Asset Review Queue. "
            "Compares each image's resolution, aspect ratio, and a cheap dominant-color proxy "
            "against the rest of that set, flagging clear statistical outliers. This is a "
            "relative/statistical heuristic, NOT true style understanding -- Spiced has no model "
            "of art style, linework, or shading technique. Treat every flag as worth a second "
            "look, never a verdict."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        row.addStretch(1)
        self._style_run_btn = PillButton("Check style consistency")
        self._style_run_btn.clicked.connect(self._on_style_run)
        row.addWidget(self._style_run_btn)
        layout.addLayout(row)

        self._style_result = QTextEdit()
        self._style_result.setReadOnly(True)
        self._style_result.setPlaceholderText("Statistical outlier findings will appear here.")
        self._style_result.setFixedHeight(160)
        layout.addWidget(self._style_result)

    def _on_style_run(self) -> None:
        paths = self._collect_review_paths()
        image_paths = [
            p for p in paths
            if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tif", ".tiff")
        ]
        if len(image_paths) < 3:
            QMessageBox.information(
                self,
                "Not enough images",
                "Load at least 3 images above (Asset Review Queue's file/folder picker) for a "
                "meaningful style comparison.",
            )
            return
        self._style_run_btn.setEnabled(False)
        self._style_run_btn.setText("Checking…")
        self._style_result.setPlainText("Comparing images…")

        worker = _StyleConsistencyWorker(self._services, image_paths)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_style_done)
        worker.failed.connect(self._on_style_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_style_done(self, result: StyleConsistencyResult) -> None:
        self._style_run_btn.setEnabled(True)
        self._style_run_btn.setText("Check style consistency")
        self._style_result.setPlainText(_format_style_result(result))

    def _on_style_failed(self, message: str) -> None:
        self._style_run_btn.setEnabled(True)
        self._style_run_btn.setText("Check style consistency")
        self._style_result.setPlainText(message)

    # --- In-Engine Placement Preview (scoped down -- see core.placement_preview)

    def _build_placement_preview(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Placement Preview (rough mockup, not a real render)")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "NOT an in-engine render -- Spiced never runs the Unity engine to render a scene. "
            "This is a rough 2D image composite only: pick a background reference image (e.g. an "
            "existing screenshot) and a new asset image, and Spiced pastes the asset onto the "
            "background at the position/scale you set below. Lighting, shading, camera "
            "perspective, and gameplay collision are not represented."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        pick_row = QHBoxLayout()
        self._bg_pick_btn = PillButton("Pick background image…")
        self._bg_pick_btn.clicked.connect(self._on_pick_background)
        pick_row.addWidget(self._bg_pick_btn)
        self._asset_pick_btn = PillButton("Pick asset image…")
        self._asset_pick_btn.clicked.connect(self._on_pick_placement_asset)
        pick_row.addWidget(self._asset_pick_btn)
        layout.addLayout(pick_row)

        self._placement_files_label = QLabel("No background/asset picked yet.")
        self._placement_files_label.setObjectName("Muted")
        self._placement_files_label.setWordWrap(True)
        layout.addWidget(self._placement_files_label)

        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("X:"))
        self._pos_x_input = QSpinBox()
        self._pos_x_input.setRange(0, 20000)
        pos_row.addWidget(self._pos_x_input)
        pos_row.addWidget(QLabel("Y:"))
        self._pos_y_input = QSpinBox()
        self._pos_y_input.setRange(0, 20000)
        pos_row.addWidget(self._pos_y_input)
        pos_row.addWidget(QLabel("Scale %:"))
        self._scale_input = QSpinBox()
        self._scale_input.setRange(1, 500)
        self._scale_input.setValue(100)
        pos_row.addWidget(self._scale_input)
        self._center_checkbox_btn = PillButton("Center on background")
        self._center_checkbox_btn.setCheckable(True)
        self._center_checkbox_btn.setChecked(True)
        pos_row.addWidget(self._center_checkbox_btn)
        pos_row.addStretch(1)
        layout.addLayout(pos_row)

        row = QHBoxLayout()
        row.addStretch(1)
        self._placement_run_btn = PillButton("Create preview…")
        self._placement_run_btn.clicked.connect(self._on_create_placement_preview)
        row.addWidget(self._placement_run_btn)
        layout.addLayout(row)

        self._placement_result = QLabel(PLACEMENT_PREVIEW_DISCLAIMER)
        self._placement_result.setObjectName("Muted")
        self._placement_result.setWordWrap(True)
        layout.addWidget(self._placement_result)

    def _on_pick_background(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a background reference image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self._placement_background = path
            self._update_placement_files_label()

    def _on_pick_placement_asset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick the new asset image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self._placement_asset = path
            self._update_placement_files_label()

    def _update_placement_files_label(self) -> None:
        bg = Path(self._placement_background).name if self._placement_background else "(none)"
        asset = Path(self._placement_asset).name if self._placement_asset else "(none)"
        self._placement_files_label.setText(f"Background: {bg}    Asset: {asset}")

    def _on_create_placement_preview(self) -> None:
        if not self._placement_background or not self._placement_asset:
            QMessageBox.information(
                self, "Pick both images", "Pick a background image and an asset image first."
            )
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Save placement preview mockup as…", "placement_preview.png", "PNG (*.png)"
        )
        if not output_path:
            return
        scale = self._scale_input.value() / 100.0
        x = None if self._center_checkbox_btn.isChecked() else self._pos_x_input.value()
        y = None if self._center_checkbox_btn.isChecked() else self._pos_y_input.value()
        try:
            result = create_placement_preview(
                self._placement_background, self._placement_asset, output_path,
                x=x, y=y, scale=scale,
            )
        except PlacementUnreadableImageError as exc:
            QMessageBox.warning(self, "Couldn't create the preview", str(exc))
            return
        self._services.record_telemetry_event("art.placement_preview_run")
        self._render_placement_result(result)

    def _render_placement_result(self, result: PlacementPreviewResult) -> None:
        self._placement_result.setText(
            f"Saved to {result.output_path} (asset placed at {result.position}, "
            f"scale {result.scale:.2f}x, on a {result.background_size[0]}x"
            f"{result.background_size[1]} background).\n\n{result.disclaimer}"
        )

    # --- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to "
                "save review runs and enable .meta introspection for assets under its Assets/ "
                "folder."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")
        self._refresh_review_history()
