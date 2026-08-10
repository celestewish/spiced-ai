"""Art: Asset Review Queue, Style Consistency Checker, In-Engine Placement
Preview, Asset Technical QA Scan.

The first three sections are local/deterministic -- no AI provider is used
anywhere on this screen. Recursive folder scans still run on a worker
thread (via ``ui.thread_utils.launch_worker``) purely for UI responsiveness,
the same pattern the Asset Optimization Sweep and Localization Readiness
scans use even though they, too, involve no AI call.

Asset Technical QA Scan (SPICED_IMPLEMENTATION_BIBLE.md, Feature 3) is the
third feature on the Bible's live-engine-integration track: it reuses the
Asset Review Queue's already-built checks above (resolution, file size,
format, mipmaps) rather than duplicating them, and adds naming-convention
checking plus (only when this project has a connected Unity folder with a
resolvable Editor) a live mesh-pivot check.
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
from spiced.automation.asset_technical_qa import DEFAULT_NAMING_PATTERN, DEFAULT_PIVOT_TOLERANCE
from spiced.automation.finding import Finding
from spiced.automation.palette_drift import (
    DEFAULT_DELTA_E_THRESHOLD,
    NoReferencePaletteError,
)
from spiced.automation.uv_lod_generation import (
    DEFAULT_LOD_RATIOS,
    SUPPORTED_EXTENSIONS,
    UvLodRunResult,
)
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
from spiced.core.unity_test_runner import resolve_unity_editor
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.progress_trail import ProgressTrail
from spiced.ui.widgets.tool_switcher import build_tool_switcher

_PALETTE_COLOR_ID_ROLE = 0x0100


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


class _AssetTechnicalQaWorker(QObject):
    done = Signal(object)  # Finding
    failed = Signal(str)

    def __init__(self, services: Services, project, folder: str) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._folder = folder

    def run(self) -> None:
        try:
            unity_path = None
            if self._project.path:
                required_version = self._project.engine_metadata.get("unity_version")
                editor = resolve_unity_editor(
                    required_version, self._project.unity_editor_path_override
                )
                unity_path = editor.path if editor is not None else None
            finding, _record = self._services.asset_technical_qa.scan(
                self._project, self._folder, unity_path=unity_path
            )
            self._services.record_telemetry_event("art.asset_technical_qa_run")
            self.done.emit(finding)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while scanning assets: {exc}")


def _format_asset_technical_qa(finding: Finding) -> str:
    lines = [finding.summary, ""]
    if not finding.items:
        lines.append("No assets were scanned.")
        return "\n".join(lines)
    for item in finding.items:
        lines.append(f"- [{item.severity}] {item.message}")
    return "\n".join(lines)


class _PaletteDriftWorker(QObject):
    done = Signal(object)  # Finding
    failed = Signal(str)

    def __init__(self, services: Services, project, folder: str) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._folder = folder

    def run(self) -> None:
        try:
            finding, _record = self._services.palette_drift.scan(self._project, self._folder)
            self._services.record_telemetry_event("art.palette_drift_run")
            self.done.emit(finding)
        except NoReferencePaletteError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while checking palettes: {exc}")


def _format_palette_drift(finding: Finding) -> str:
    lines = [finding.summary, ""]
    if not finding.items:
        lines.append("No images were checked.")
        return "\n".join(lines)
    for item in finding.items:
        lines.append(f"- [{item.severity}] {item.message}")
    return "\n".join(lines)


class _UvLodGenerationWorker(QObject):
    """Emits ``progress`` (Live Task Progress Transparency) with a
    plain-language description of each LOD level as it's generated -- see
    ``ui.widgets.progress_trail``. This is exactly the kind of multi-minute
    action (simplify + unwrap, per LOD level, each in its own subprocess)
    worth naming steps for, not just a bare spinner."""

    done = Signal(object)  # UvLodRunResult
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        services: Services,
        project,
        mesh_path: str,
        output_dir: str,
        ratios: tuple[float, ...],
    ) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._mesh_path = mesh_path
        self._output_dir = output_dir
        self._ratios = ratios

    def run(self) -> None:
        try:
            result = self._services.uv_lod_generation.generate(
                self._project,
                self._mesh_path,
                output_dir=self._output_dir,
                ratios=self._ratios,
                on_progress=self.progress.emit,
            )
            self._services.record_telemetry_event("art.uv_lod_generation_run")
            self.done.emit(result)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while generating UVs/LODs: {exc}")


def _format_uv_lod_generation(finding: Finding) -> str:
    lines = [finding.summary, ""]
    if not finding.items:
        lines.append("No LOD levels were generated.")
        return "\n".join(lines)
    for item in finding.items:
        lines.append(f"- [{item.severity}] {item.message}")
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
                ("Asset Technical QA Scan", self._build_asset_technical_qa),
                ("Texture & Palette Drift Detection", self._build_palette_drift),
                ("UV Unwrapping + LOD Generation", self._build_uv_lod_generation),
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
            "Pick files, or paste a folder path, to review. Spiced runs local checks (no AI, "
            "same result every time): power-of-two resolution (a heads-up, not a hard rule), "
            "file-size sanity, source-only format warnings, and (for assets under this "
            "project's Assets/ folder) .meta introspection -- mipmap setting and a "
            "missing-.meta flag. Automated technical checks only, never an art-direction review."
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
            "against the rest of that set, flagging clear outliers. This is a relative "
            "comparison against the set, not true style understanding -- Spiced has no model "
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

    # --- Asset Technical QA Scan (Implementation Bible, Feature 3) -----------

    def _build_asset_technical_qa(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Asset Technical QA Scan")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Check assets for technical issues before they reach a programmer: resolution/"
            "power-of-two, file-size sanity, source-only formats, and (for assets under this "
            "project's Assets/ folder) mipmap settings -- reusing the same checks as the Asset "
            "Review Queue above. Naming convention is checked against a per-project regex. Mesh "
            "pivot offset is also checked when this project has a connected Unity folder with a "
            "resolvable Editor -- that one check needs to load the mesh in Unity, since pivot "
            "isn't reliably readable from the raw file."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._atq_folder_input = QLineEdit()
        self._atq_folder_input.setPlaceholderText("Folder of assets to scan")
        row.addWidget(self._atq_folder_input, 1)
        self._atq_browse_btn = PillButton("Browse…")
        self._atq_browse_btn.clicked.connect(self._on_atq_browse)
        row.addWidget(self._atq_browse_btn)
        layout.addLayout(row)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Naming pattern:"))
        self._atq_naming_input = QLineEdit()
        self._atq_naming_input.setPlaceholderText(DEFAULT_NAMING_PATTERN)
        settings_row.addWidget(self._atq_naming_input, 1)
        settings_row.addWidget(QLabel("Pivot tolerance:"))
        self._atq_tolerance_input = QLineEdit()
        self._atq_tolerance_input.setFixedWidth(60)
        self._atq_tolerance_input.setPlaceholderText(str(DEFAULT_PIVOT_TOLERANCE))
        settings_row.addWidget(self._atq_tolerance_input)
        self._atq_save_settings_btn = PillButton("Save as project default", ghost=True)
        self._atq_save_settings_btn.clicked.connect(self._on_atq_save_settings)
        settings_row.addWidget(self._atq_save_settings_btn)
        layout.addLayout(settings_row)

        run_row = QHBoxLayout()
        run_row.addStretch(1)
        self._atq_run_btn = PillButton("Scan assets")
        self._atq_run_btn.clicked.connect(self._on_atq_run)
        run_row.addWidget(self._atq_run_btn)
        layout.addLayout(run_row)

        self._atq_result = QTextEdit()
        self._atq_result.setReadOnly(True)
        self._atq_result.setPlaceholderText("Per-asset technical QA findings will appear here.")
        self._atq_result.setFixedHeight(220)
        layout.addWidget(self._atq_result)

        history_title = QLabel("Recent scans")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._atq_history = QTextEdit()
        self._atq_history.setReadOnly(True)
        self._atq_history.setFixedHeight(80)
        layout.addWidget(self._atq_history)

    def _on_atq_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick a folder of assets to scan")
        if folder:
            self._atq_folder_input.setText(folder)

    def _atq_naming_pattern_from_field(self) -> str | None:
        text = self._atq_naming_input.text().strip()
        return text or None

    def _atq_tolerance_from_field(self) -> float | None:
        """Raises ValueError for unparseable (non-blank) input."""
        text = self._atq_tolerance_input.text().strip()
        return float(text) if text else None

    def _on_atq_save_settings(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        try:
            tolerance = self._atq_tolerance_from_field()
        except ValueError:
            QMessageBox.information(
                self, "Invalid tolerance", "Pivot tolerance must be a number, e.g. 0.1."
            )
            return
        self._services.projects.set_asset_qa_settings(
            project.id, self._atq_naming_pattern_from_field(), tolerance
        )
        self.refresh()

    def _on_atq_run(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        folder = self._atq_folder_input.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.information(
                self, "Pick a folder", "Enter or browse to a folder containing assets first."
            )
            return
        self._atq_run_btn.setEnabled(False)
        self._atq_run_btn.setText("Scanning…")
        self._atq_result.setPlainText("Scanning assets…")

        worker = _AssetTechnicalQaWorker(self._services, project, folder)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_atq_done)
        worker.failed.connect(self._on_atq_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_atq_done(self, finding: Finding) -> None:
        self._atq_run_btn.setEnabled(True)
        self._atq_run_btn.setText("Scan assets")
        self._atq_result.setPlainText(_format_asset_technical_qa(finding))
        self.usage_changed.emit()
        self._refresh_atq_history()

    def _on_atq_failed(self, message: str) -> None:
        self._atq_run_btn.setEnabled(True)
        self._atq_run_btn.setText("Scan assets")
        self._atq_result.setPlainText(message)

    def _refresh_atq_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._atq_history.setPlainText("Runs are saved once you select an active project.")
            return
        records = self._services.asset_technical_qa.history(project.id, limit=5)
        if not records:
            self._atq_history.setPlainText("No scans saved yet.")
            return
        self._atq_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
        )

    # --- Texture & Palette Drift Detection (Implementation Bible, Feature 4) ---

    def _build_palette_drift(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Texture & Palette Drift Detection")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Does this asset's palette match our existing style reference? Each image's "
            "dominant colors (k-means) are compared to a reference palette by average "
            "nearest-color distance in Lab color space (Delta-E) -- flagged when it drifts "
            "past the threshold below. Build the reference by adding hex colors directly, or "
            "by pointing at a folder of approved assets."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        ref_title = QLabel("Reference palette")
        ref_title.setObjectName("SectionTitle")
        layout.addWidget(ref_title)

        ref_add_row = QHBoxLayout()
        self._palette_hex_input = QLineEdit()
        self._palette_hex_input.setPlaceholderText("#3366CC")
        ref_add_row.addWidget(self._palette_hex_input, 1)
        self._palette_add_btn = PillButton("Add color")
        self._palette_add_btn.clicked.connect(self._on_palette_add_color)
        ref_add_row.addWidget(self._palette_add_btn)
        self._palette_folder_btn = PillButton("Set from folder…", ghost=True)
        self._palette_folder_btn.clicked.connect(self._on_palette_set_from_folder)
        ref_add_row.addWidget(self._palette_folder_btn)
        layout.addLayout(ref_add_row)

        self._palette_list = QListWidget()
        self._palette_list.setFixedHeight(80)
        layout.addWidget(self._palette_list)

        remove_row = QHBoxLayout()
        remove_row.addStretch(1)
        self._palette_remove_btn = PillButton("Remove selected", ghost=True)
        self._palette_remove_btn.clicked.connect(self._on_palette_remove_color)
        remove_row.addWidget(self._palette_remove_btn)
        layout.addLayout(remove_row)

        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Delta-E threshold:"))
        self._palette_threshold_input = QLineEdit()
        self._palette_threshold_input.setFixedWidth(60)
        self._palette_threshold_input.setPlaceholderText(str(DEFAULT_DELTA_E_THRESHOLD))
        threshold_row.addWidget(self._palette_threshold_input)
        self._palette_save_threshold_btn = PillButton("Save as project default", ghost=True)
        self._palette_save_threshold_btn.clicked.connect(self._on_palette_save_threshold)
        threshold_row.addWidget(self._palette_save_threshold_btn)
        threshold_row.addStretch(1)
        layout.addLayout(threshold_row)

        scan_title = QLabel("Check assets")
        scan_title.setObjectName("SectionTitle")
        layout.addWidget(scan_title)

        scan_row = QHBoxLayout()
        self._palette_scan_folder_input = QLineEdit()
        self._palette_scan_folder_input.setPlaceholderText("Folder of assets to check")
        scan_row.addWidget(self._palette_scan_folder_input, 1)
        self._palette_scan_browse_btn = PillButton("Browse…")
        self._palette_scan_browse_btn.clicked.connect(self._on_palette_scan_browse)
        scan_row.addWidget(self._palette_scan_browse_btn)
        self._palette_run_btn = PillButton("Check palettes")
        self._palette_run_btn.clicked.connect(self._on_palette_run)
        scan_row.addWidget(self._palette_run_btn)
        layout.addLayout(scan_row)

        self._palette_result = QTextEdit()
        self._palette_result.setReadOnly(True)
        self._palette_result.setPlaceholderText(
            "Per-asset palette drift findings will appear here."
        )
        self._palette_result.setFixedHeight(200)
        layout.addWidget(self._palette_result)

        history_title = QLabel("Recent checks")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._palette_history = QTextEdit()
        self._palette_history.setReadOnly(True)
        self._palette_history.setFixedHeight(80)
        layout.addWidget(self._palette_history)

    def _on_palette_add_color(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        hex_color = self._palette_hex_input.text().strip()
        if not hex_color:
            return
        try:
            self._services.palette_drift.add_reference_color(project.id, hex_color)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid color", str(exc))
            return
        self._palette_hex_input.clear()
        self._refresh_palette_reference_list()

    def _on_palette_remove_color(self) -> None:
        item = self._palette_list.currentItem()
        if item is None:
            return
        color_id = item.data(_PALETTE_COLOR_ID_ROLE)
        self._services.palette_drift.remove_reference_color(color_id)
        self._refresh_palette_reference_list()

    def _on_palette_set_from_folder(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Pick a reference folder of approved assets"
        )
        if not folder:
            return
        try:
            self._services.palette_drift.set_reference_from_folder(project.id, folder)
        except NoReferencePaletteError as exc:
            QMessageBox.warning(self, "Couldn't set reference palette", str(exc))
            return
        self._refresh_palette_reference_list()

    def _refresh_palette_reference_list(self) -> None:
        self._palette_list.clear()
        project = self._services.active_project()
        if project is None:
            return
        for color in self._services.palette_drift.list_reference_colors(project.id):
            item = QListWidgetItem(color.hex_color)
            item.setData(_PALETTE_COLOR_ID_ROLE, color.id)
            self._palette_list.addItem(item)

    def _on_palette_save_threshold(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        text = self._palette_threshold_input.text().strip()
        try:
            threshold = float(text) if text else None
        except ValueError:
            QMessageBox.information(
                self, "Invalid threshold", "Delta-E threshold must be a number, e.g. 15."
            )
            return
        self._services.projects.set_palette_drift_threshold(project.id, threshold)
        self.refresh()

    def _on_palette_scan_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick a folder of assets to check")
        if folder:
            self._palette_scan_folder_input.setText(folder)

    def _on_palette_run(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        folder = self._palette_scan_folder_input.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.information(
                self, "Pick a folder", "Enter or browse to a folder containing assets first."
            )
            return
        self._palette_run_btn.setEnabled(False)
        self._palette_run_btn.setText("Checking…")
        self._palette_result.setPlainText("Checking palettes…")

        worker = _PaletteDriftWorker(self._services, project, folder)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_palette_done)
        worker.failed.connect(self._on_palette_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_palette_done(self, finding: Finding) -> None:
        self._palette_run_btn.setEnabled(True)
        self._palette_run_btn.setText("Check palettes")
        self._palette_result.setPlainText(_format_palette_drift(finding))
        self.usage_changed.emit()
        self._refresh_palette_history()

    def _on_palette_failed(self, message: str) -> None:
        self._palette_run_btn.setEnabled(True)
        self._palette_run_btn.setText("Check palettes")
        self._palette_result.setPlainText(message)

    def _refresh_palette_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._palette_history.setPlainText("Runs are saved once you select an active project.")
            return
        records = self._services.palette_drift.history(project.id, limit=5)
        if not records:
            self._palette_history.setPlainText("No palette checks saved yet.")
            return
        self._palette_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
        )

    # --- UV Unwrapping + LOD Generation (Implementation Bible, Feature 8) ------

    def _build_uv_lod_generation(self, layout: QVBoxLayout) -> None:
        heading = QLabel("UV Unwrapping + LOD Generation")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Auto-unwrap UVs and generate LODs for this model: xatlas unwraps UVs (guaranteed "
            "non-overlapping charts) and meshoptimizer simplifies the mesh at each ratio below "
            "(borders locked so LOD seams don't reopen). Each LOD level is exported as its own "
            f"file. Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))} only -- .fbx has "
            "no reliable pure-Python loader; export an OBJ/glTF copy first."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        mesh_row = QHBoxLayout()
        self._uld_mesh_input = QLineEdit()
        self._uld_mesh_input.setPlaceholderText("Source mesh file (.obj/.gltf/.glb)")
        mesh_row.addWidget(self._uld_mesh_input, 1)
        self._uld_mesh_browse_btn = PillButton("Browse…")
        self._uld_mesh_browse_btn.clicked.connect(self._on_uld_browse_mesh)
        mesh_row.addWidget(self._uld_mesh_browse_btn)
        layout.addLayout(mesh_row)

        output_row = QHBoxLayout()
        self._uld_output_input = QLineEdit()
        self._uld_output_input.setPlaceholderText("Output folder for generated LOD files")
        output_row.addWidget(self._uld_output_input, 1)
        self._uld_output_browse_btn = PillButton("Browse…")
        self._uld_output_browse_btn.clicked.connect(self._on_uld_browse_output)
        output_row.addWidget(self._uld_output_browse_btn)
        layout.addLayout(output_row)

        ratios_row = QHBoxLayout()
        ratios_row.addWidget(QLabel("LOD ratios:"))
        self._uld_ratios_input = QLineEdit()
        self._uld_ratios_input.setPlaceholderText(
            ", ".join(str(r) for r in DEFAULT_LOD_RATIOS)
        )
        ratios_row.addWidget(self._uld_ratios_input, 1)
        ratios_row.addStretch(1)
        self._uld_run_btn = PillButton("Generate UVs && LODs")
        self._uld_run_btn.clicked.connect(self._on_uld_run)
        ratios_row.addWidget(self._uld_run_btn)
        layout.addLayout(ratios_row)

        self._uld_progress_trail = ProgressTrail()
        layout.addWidget(self._uld_progress_trail)

        self._uld_result = QTextEdit()
        self._uld_result.setReadOnly(True)
        self._uld_result.setPlaceholderText("Per-LOD UV/triangle findings will appear here.")
        self._uld_result.setFixedHeight(200)
        layout.addWidget(self._uld_result)

        history_title = QLabel("Recent runs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._uld_history = QTextEdit()
        self._uld_history.setReadOnly(True)
        self._uld_history.setFixedHeight(80)
        layout.addWidget(self._uld_history)

    def _on_uld_browse_mesh(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a source mesh", "", "Meshes (*.obj *.gltf *.glb)"
        )
        if path:
            self._uld_mesh_input.setText(path)

    def _on_uld_browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick an output folder")
        if folder:
            self._uld_output_input.setText(folder)

    def _uld_ratios_from_field(self) -> tuple[float, ...]:
        """Raises ValueError for unparseable (non-blank) input."""
        text = self._uld_ratios_input.text().strip()
        if not text:
            return DEFAULT_LOD_RATIOS
        return tuple(float(part.strip()) for part in text.split(","))

    def _on_uld_run(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        mesh_path = self._uld_mesh_input.text().strip()
        output_dir = self._uld_output_input.text().strip()
        if not mesh_path or not Path(mesh_path).is_file():
            QMessageBox.information(
                self, "Pick a mesh", "Enter or browse to a source mesh file first."
            )
            return
        if not output_dir:
            QMessageBox.information(
                self, "Pick an output folder", "Enter or browse to an output folder first."
            )
            return
        try:
            ratios = self._uld_ratios_from_field()
        except ValueError:
            QMessageBox.information(
                self, "Invalid ratios", "LOD ratios must be numbers, e.g. 1.0, 0.5, 0.25, 0.1."
            )
            return

        self._uld_run_btn.setEnabled(False)
        self._uld_run_btn.setText("Generating…")
        self._uld_result.setPlainText("Generating UVs and LODs (this can take a while)…")
        self._uld_progress_trail.reset()

        worker = _UvLodGenerationWorker(self._services, project, mesh_path, output_dir, ratios)
        thread = launch_worker(self, worker, progress_slot=self._uld_progress_trail.add_step)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_uld_done)
        worker.failed.connect(self._on_uld_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_uld_done(self, result: UvLodRunResult) -> None:
        self._uld_run_btn.setEnabled(True)
        self._uld_run_btn.setText("Generate UVs && LODs")
        self._uld_result.setPlainText(_format_uv_lod_generation(result.finding))
        self.usage_changed.emit()
        self._refresh_uld_history()

    def _on_uld_failed(self, message: str) -> None:
        self._uld_run_btn.setEnabled(True)
        self._uld_run_btn.setText("Generate UVs && LODs")
        self._uld_result.setPlainText(message)

    def _refresh_uld_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._uld_history.setPlainText("Runs are saved once you select an active project.")
            return
        records = self._services.uv_lod_generation.history(project.id, limit=5)
        if not records:
            self._uld_history.setPlainText("No runs saved yet.")
            return
        self._uld_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
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
        self._refresh_atq_history()
        self._refresh_palette_reference_list()
        self._refresh_palette_history()
        self._refresh_uld_history()
        if project is not None:
            self._atq_naming_input.setText(project.asset_naming_pattern or "")
            self._atq_tolerance_input.setText(
                "" if project.asset_pivot_tolerance is None else str(project.asset_pivot_tolerance)
            )
            self._palette_threshold_input.setText(
                ""
                if project.palette_drift_threshold is None
                else str(project.palette_drift_threshold)
            )
