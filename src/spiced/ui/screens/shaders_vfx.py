"""Shaders/VFX: Shader Performance Profiling, Visual Regression Testing
(paste/import), Visual Regression Testing (Live Capture).

The first two sections are local, deterministic scans -- no AI provider or
engine connection is used anywhere on this screen. Scans run on a worker
thread via ``ui.thread_utils.launch_worker`` for UI responsiveness, same as
every other recursive/batch scan in this codebase.

Visual Regression Testing (Live Capture) (SPICED_IMPLEMENTATION_BIBLE.md,
Feature 2) is the second feature on the Bible's live-engine-integration
track: unlike the paste/import section above, it launches a real headless
Unity Editor to screenshot the project's own key scenes (see
``docs/visual_regression_capture_hook.md`` for the marker-GameObject
convention) rather than only diffing screenshots the developer picked by
hand -- everything else about how it's wired into this screen (worker
thread, run button, result panel, saved-run history) still matches the
sections above.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.automation.finding import Finding
from spiced.automation.gpu_shader_profiling import DEFAULT_HARDWARE_TIER, GpuProfilingRunResult
from spiced.automation.shader_variant_analysis import DEFAULT_VARIANT_THRESHOLD
from spiced.automation.visual_regression_capture import NoKeyScenesError, UnityUnavailableError
from spiced.core.hardware_simulation import HARDWARE_TIERS
from spiced.core.shader_performance_profiling import (
    NoUnityFolderError as ShaderNoUnityFolderError,
)
from spiced.core.shader_performance_profiling import ShaderProfilingResult
from spiced.core.unity_test_runner import resolve_unity_editor
from spiced.core.visual_regression import UnreadableImageError, VisualRegressionResult
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.diff_viewer import DiffViewerDialog
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.scroll_safe_combo_box import ScrollSafeComboBox
from spiced.ui.widgets.tool_switcher import build_tool_switcher


class _ShaderProfilingWorker(QObject):
    done = Signal(object)  # ShaderProfilingResult
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            result, _report = self._services.shader_performance_profiling.scan(self._project)
            self._services.record_telemetry_event("shaders_vfx.shader_profiling_run")
            self.done.emit(result)
        except ShaderNoUnityFolderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while scanning: {exc}")


class _VisualRegressionWorker(QObject):
    done = Signal(object)  # VisualRegressionResult
    failed = Signal(str)

    def __init__(self, services: Services, project, before_dir: str, after_dir: str) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._before_dir = before_dir
        self._after_dir = after_dir

    def run(self) -> None:
        try:
            result, _report = self._services.visual_regression.diff(
                self._project, self._before_dir, self._after_dir
            )
            self._services.record_telemetry_event("shaders_vfx.visual_regression_run")
            self.done.emit(result)
        except UnreadableImageError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while diffing screenshots: {exc}")


class _VisualRegressionCaptureWorker(QObject):
    done = Signal(object)  # Finding
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            required_version = self._project.engine_metadata.get("unity_version")
            editor = resolve_unity_editor(
                required_version, self._project.unity_editor_path_override
            )
            if editor is None:
                self.failed.emit(
                    f"Unity {required_version or '(unknown version)'} isn't available. Install "
                    "it via Unity Hub, or set a manual Editor path on the Projects screen."
                )
                return
            finding, _record = self._services.visual_regression_capture.run(
                self._project, editor.path
            )
            self._services.record_telemetry_event("shaders_vfx.visual_regression_capture_run")
            self.done.emit(finding)
        except (NoKeyScenesError, UnityUnavailableError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during capture: {exc}")


def _format_visual_regression_capture(finding: Finding) -> str:
    lines = [finding.summary, ""]
    if not finding.items:
        lines.append("No key scenes were captured.")
        return "\n".join(lines)
    for item in finding.items:
        lines.append(f"- [{item.severity}] {item.message}")
        diff_image = item.detail.get("diff_image")
        if diff_image:
            lines.append(f"    · diff image saved to {diff_image}")
    return "\n".join(lines)


class _ShaderVariantAnalysisWorker(QObject):
    done = Signal(object)  # Finding
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            required_version = self._project.engine_metadata.get("unity_version")
            editor = resolve_unity_editor(
                required_version, self._project.unity_editor_path_override
            )
            if editor is None:
                self.failed.emit(
                    f"Unity {required_version or '(unknown version)'} isn't available. Install "
                    "it via Unity Hub, or set a manual Editor path on the Projects screen."
                )
                return
            finding, _record = self._services.shader_variant_analysis.scan(
                self._project, editor.path
            )
            self._services.record_telemetry_event("shaders_vfx.shader_variant_analysis_run")
            self.done.emit(finding)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while analyzing shader variants: {exc}")


def _format_shader_variant_analysis(finding: Finding) -> str:
    lines = [finding.summary, ""]
    if not finding.items:
        lines.append("No shaders were analyzed.")
        return "\n".join(lines)
    for item in finding.items:
        rank = item.detail.get("top_offender_rank")
        prefix = f"#{rank} " if rank else ""
        lines.append(f"- {prefix}[{item.severity}] {item.message}")
        if "estimated_compile_time_ms" in item.detail:
            lines.append(
                f"    · estimated compile time: {item.detail['estimated_compile_time_ms']:.0f}ms"
            )
    return "\n".join(lines)


class _GpuShaderProfilingWorker(QObject):
    done = Signal(object)  # GpuProfilingRunResult
    failed = Signal(str)

    def __init__(
        self, services: Services, project, rdc_path: str, pymodules_path: str, tier: str
    ) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._rdc_path = rdc_path
        self._pymodules_path = pymodules_path
        self._tier = tier

    def run(self) -> None:
        try:
            result, _record = self._services.gpu_shader_profiling.profile(
                self._project, self._rdc_path, self._pymodules_path, tier=self._tier
            )
            self._services.record_telemetry_event("shaders_vfx.gpu_shader_profiling_run")
            self.done.emit(result)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while analyzing the capture: {exc}")


def _format_gpu_shader_profiling(finding: Finding) -> str:
    lines = [finding.summary, ""]
    if not finding.items:
        lines.append("No shaders were found in the capture.")
        return "\n".join(lines)
    for item in finding.items:
        rank = item.detail.get("top_offender_rank")
        prefix = f"#{rank} " if rank else ""
        lines.append(f"- {prefix}[{item.severity}] {item.message}")
    return "\n".join(lines)


def _format_shader_profiling(result: ShaderProfilingResult) -> str:
    lines = [result.caveat, ""]
    lines.append(f"{len(result.shaders)} .shader file(s) scanned.")
    lines.append("")
    if result.shaders:
        for s in result.shaders:
            flag = " ⚠ likely expensive" if s.likely_expensive else ""
            lines.append(
                f"- {s.path}: {s.sampler_count} sampler(s), {s.pass_count} pass(es), "
                f"{s.loop_count} loop(s), {s.max_lines_in_pass} lines/pass{flag}"
            )
            if s.likely_expensive:
                for reason in s.reasons:
                    lines.append(f"    · {reason}")
                tiers = ", ".join(s.at_risk_tiers)
                lines.append(f"    · flagged as likely too expensive for: {tiers}")
    else:
        lines.append("No .shader files found.")
    lines.append("")
    lines.append(f"{len(result.shader_graphs)} .shadergraph (Shader Graph) file(s) detected:")
    if result.shader_graphs:
        for g in result.shader_graphs:
            lines.append(f"- {g.path}: {g.note}")
    else:
        lines.append("None found.")
    lines.append("")
    lines.append(
        "See the Automated Testing screen's Performance & Profiling section (Cross-Platform "
        "Test Simulation) for the same hardware-tier framing applied to your measured fps -- "
        "shaders flagged above as likely too expensive for a tier are worth cross-checking "
        "against any at-risk locations that simulation already found."
    )
    return "\n".join(lines)


def _format_visual_regression(result: VisualRegressionResult) -> str:
    lines = [result.caveat, ""]
    lines.append(f"{len(result.pairs)} matched pair(s), {result.changed_count} flagged as changed.")
    lines.append("")
    for p in result.pairs:
        flag = " ⚠ changed" if p.changed else ""
        size_note = " (size mismatch)" if p.size_mismatch else ""
        lines.append(
            f"- {p.name}: {p.changed_pixel_ratio * 100:.1f}% pixels changed{flag}{size_note}"
        )
        if p.diff_image_path:
            lines.append(f"    · diff image saved to {p.diff_image_path}")
    if result.unmatched_before:
        lines.append("")
        lines.append("Only in the 'before' folder (no matching filename in 'after'):")
        for name in result.unmatched_before:
            lines.append(f"- {name}")
    if result.unmatched_after:
        lines.append("")
        lines.append("Only in the 'after' folder (no matching filename in 'before'):")
        for name in result.unmatched_after:
            lines.append(f"- {name}")
    return "\n".join(lines)


class ShadersVfxScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._before_dir = ""
        self._after_dir = ""
        self._vr_pairs_by_name: dict[str, object] = {}

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

        title = QLabel("Shaders/VFX")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        columns, self._stack, self._tool_group = build_tool_switcher(
            self,
            [
                ("Shader Performance Profiling", self._build_shader_profiling),
                ("Visual Regression Testing", self._build_visual_regression),
                ("Visual Regression Testing (Live Capture)", self._build_visual_regression_capture),
                ("Shader Variant & Compile Bloat Analysis", self._build_shader_variant_analysis),
                ("Shader Performance Profiling (GPU Capture)", self._build_gpu_shader_profiling),
            ],
        )
        layout.addLayout(columns, 1)

        self.refresh()

    # --- Shader Performance Profiling ---------------------------------------

    def _build_shader_profiling(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Shader Performance Profiling")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Scans this project's .shader files for complexity indicators (texture sampler "
            "count, Pass block count, loop constructs, and a rough line-count-per-Pass proxy) "
            "-- Spiced never compiles or profiles shaders on real hardware. .shadergraph (Shader "
            "Graph) assets are detected but not deeply analyzed -- see the results for why."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        row.addStretch(1)
        self._shader_run_btn = PillButton("Scan shaders")
        self._shader_run_btn.clicked.connect(self._on_shader_scan_run)
        row.addWidget(self._shader_run_btn)
        layout.addLayout(row)

        self._shader_result = QTextEdit()
        self._shader_result.setReadOnly(True)
        self._shader_result.setPlaceholderText("Shader complexity findings will appear here.")
        self._shader_result.setFixedHeight(240)
        layout.addWidget(self._shader_result)

        history_title = QLabel("Recent scans")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._shader_history = QTextEdit()
        self._shader_history.setReadOnly(True)
        self._shader_history.setFixedHeight(80)
        layout.addWidget(self._shader_history)

    def _on_shader_scan_run(self) -> None:
        project = self._services.active_project()
        if project is None or not project.path:
            QMessageBox.information(
                self, "Pick a project first",
                "Select a project with a connected Unity folder on the Projects screen.",
            )
            return
        self._shader_run_btn.setEnabled(False)
        self._shader_run_btn.setText("Scanning…")
        self._shader_result.setPlainText("Scanning .shader/.shadergraph files…")

        worker = _ShaderProfilingWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_shader_scan_done)
        worker.failed.connect(self._on_shader_scan_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_shader_scan_done(self, result: ShaderProfilingResult) -> None:
        self._shader_run_btn.setEnabled(True)
        self._shader_run_btn.setText("Scan shaders")
        self._shader_result.setPlainText(_format_shader_profiling(result))
        self.usage_changed.emit()
        self._refresh_shader_history()

    def _on_shader_scan_failed(self, message: str) -> None:
        self._shader_run_btn.setEnabled(True)
        self._shader_run_btn.setText("Scan shaders")
        self._shader_result.setPlainText(message)

    def _refresh_shader_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._shader_history.setPlainText("Scans are saved once you select an active project.")
            return
        reports = self._services.shader_performance_profiling.history(project.id, limit=5)
        if not reports:
            self._shader_history.setPlainText("No shader scans saved yet.")
            return
        lines = [
            f"[{r.created_at}] {r.findings.get('flagged_count', 0)} shader(s) flagged"
            for r in reports
        ]
        self._shader_history.setPlainText("\n".join(lines))

    # --- Visual Regression Testing -------------------------------------------

    def _build_visual_regression(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Visual Regression Testing")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Pick a 'before' folder and an 'after' folder of screenshots from the same key "
            "scenes across two builds -- Spiced never captures a live engine screenshot. Pairs "
            "sharing a filename are diffed locally with Pillow and flagged if they've changed "
            "noticeably; a highlighted diff image is saved for each flagged pair."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        before_row = QHBoxLayout()
        before_row.addWidget(QLabel("Before folder:"))
        self._before_input = QLineEdit()
        self._before_input.setPlaceholderText("Screenshots from the earlier build")
        before_row.addWidget(self._before_input, 1)
        before_browse = PillButton("Browse…")
        before_browse.clicked.connect(self._on_browse_before)
        before_row.addWidget(before_browse)
        layout.addLayout(before_row)

        after_row = QHBoxLayout()
        after_row.addWidget(QLabel("After folder:"))
        self._after_input = QLineEdit()
        self._after_input.setPlaceholderText("Screenshots from the newer build")
        after_row.addWidget(self._after_input, 1)
        after_browse = PillButton("Browse…")
        after_browse.clicked.connect(self._on_browse_after)
        after_row.addWidget(after_browse)
        layout.addLayout(after_row)

        run_row = QHBoxLayout()
        run_row.addStretch(1)
        self._vr_run_btn = PillButton("Diff screenshots")
        self._vr_run_btn.clicked.connect(self._on_vr_run)
        run_row.addWidget(self._vr_run_btn)
        layout.addLayout(run_row)

        self._vr_result = QTextEdit()
        self._vr_result.setReadOnly(True)
        self._vr_result.setPlaceholderText("Visual diff findings will appear here.")
        self._vr_result.setFixedHeight(240)
        layout.addWidget(self._vr_result)

        # Visual Diff Viewer (Phase L, Phase 2 tier): opens the reusable
        # DiffViewer (ui.widgets.diff_viewer) in image mode for one matched
        # pair from the run above -- a side-by-side or highlighted-overlay
        # look, rather than only the numeric changed-pixel-ratio line.
        diff_viewer_row = QHBoxLayout()
        diff_viewer_row.addWidget(QLabel("View pair:"))
        self._vr_pair_picker = ScrollSafeComboBox()
        self._vr_pair_picker.setEnabled(False)
        diff_viewer_row.addWidget(self._vr_pair_picker, 1)
        self._vr_open_diff_btn = PillButton("Open diff viewer", ghost=True)
        self._vr_open_diff_btn.setEnabled(False)
        self._vr_open_diff_btn.clicked.connect(self._on_view_diff_pair)
        diff_viewer_row.addWidget(self._vr_open_diff_btn)
        layout.addLayout(diff_viewer_row)

        history_title = QLabel("Recent diffs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._vr_history = QTextEdit()
        self._vr_history.setReadOnly(True)
        self._vr_history.setFixedHeight(80)
        layout.addWidget(self._vr_history)

    def _on_browse_before(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick the 'before' screenshots folder")
        if folder:
            self._before_input.setText(folder)

    def _on_browse_after(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick the 'after' screenshots folder")
        if folder:
            self._after_input.setText(folder)

    def _on_vr_run(self) -> None:
        before_dir = self._before_input.text().strip()
        after_dir = self._after_input.text().strip()
        if not before_dir or not after_dir:
            QMessageBox.information(
                self, "Pick both folders", "Choose a 'before' folder and an 'after' folder first."
            )
            return
        if not Path(before_dir).is_dir() or not Path(after_dir).is_dir():
            QMessageBox.warning(
                self, "Folder not found", "One of the folders you picked doesn't exist."
            )
            return

        self._vr_run_btn.setEnabled(False)
        self._vr_run_btn.setText("Diffing…")
        self._vr_result.setPlainText("Diffing matching screenshots…")

        worker = _VisualRegressionWorker(
            self._services, self._services.active_project(), before_dir, after_dir
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_vr_done)
        worker.failed.connect(self._on_vr_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_vr_done(self, result: VisualRegressionResult) -> None:
        self._vr_run_btn.setEnabled(True)
        self._vr_run_btn.setText("Diff screenshots")
        self._vr_result.setPlainText(_format_visual_regression(result))
        self.usage_changed.emit()
        self._refresh_vr_history()
        self._refresh_diff_pair_picker(result)

    def _on_vr_failed(self, message: str) -> None:
        self._vr_run_btn.setEnabled(True)
        self._vr_run_btn.setText("Diff screenshots")
        self._vr_result.setPlainText(message)
        self._refresh_diff_pair_picker(None)

    def _refresh_diff_pair_picker(self, result: VisualRegressionResult | None) -> None:
        self._vr_pairs_by_name = {p.name: p for p in result.pairs} if result else {}
        self._vr_pair_picker.clear()
        # Changed pairs first -- the ones actually worth opening a viewer for.
        ordered = sorted(self._vr_pairs_by_name.values(), key=lambda p: not p.changed)
        for pair in ordered:
            flag = " (changed)" if pair.changed else ""
            self._vr_pair_picker.addItem(f"{pair.name}{flag}", pair.name)
        has_pairs = bool(ordered)
        self._vr_pair_picker.setEnabled(has_pairs)
        self._vr_open_diff_btn.setEnabled(has_pairs)

    def _on_view_diff_pair(self) -> None:
        name = self._vr_pair_picker.currentData()
        pair = self._vr_pairs_by_name.get(name) if name else None
        if pair is None:
            return
        try:
            dialog = DiffViewerDialog.for_images(
                pair.before_path, pair.after_path, title=f"Compare: {pair.name}", parent=self
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Couldn't open diff viewer", str(exc))
            return
        dialog.exec()

    def _refresh_vr_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._vr_history.setPlainText("Diffs are saved once you select an active project.")
            return
        reports = self._services.visual_regression.history(project.id, limit=5)
        if not reports:
            self._vr_history.setPlainText("No visual regression diffs saved yet.")
            return
        lines = [
            f"[{r.created_at}] {r.findings.get('changed_count', 0)} pair(s) flagged as changed"
            for r in reports
        ]
        self._vr_history.setPlainText("\n".join(lines))

    # --- Visual Regression Testing (Live Capture) (Implementation Bible, Feature 2) ---

    def _build_visual_regression_capture(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Visual Regression Testing (Live Capture)")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Compare today's build screenshots against last week's for unexpected changes: "
            "Spiced launches a headless Unity Editor, screenshots this project's own key scenes, "
            "and flags any that changed more than 2% of their pixels vs. the previous capture. "
            "See docs/visual_regression_capture_hook.md for how to set up a key scene's capture "
            "camera position."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        add_heading = QLabel("Add a key scene")
        add_heading.setObjectName("SectionTitle")
        layout.addWidget(add_heading)

        scene_row = QHBoxLayout()
        self._vrc_scene_path_input = QLineEdit()
        self._vrc_scene_path_input.setPlaceholderText(
            "Scene path, e.g. Assets/Scenes/Main.unity"
        )
        scene_row.addWidget(self._vrc_scene_path_input, 1)
        layout.addLayout(scene_row)

        label_row = QHBoxLayout()
        self._vrc_label_input = QLineEdit()
        self._vrc_label_input.setPlaceholderText("Label, e.g. Main Hall")
        label_row.addWidget(self._vrc_label_input, 1)
        self._vrc_marker_input = QLineEdit()
        self._vrc_marker_input.setPlaceholderText("Marker GameObject name")
        label_row.addWidget(self._vrc_marker_input, 1)
        self._vrc_add_btn = PillButton("Add key scene")
        self._vrc_add_btn.clicked.connect(self._on_vrc_add_key_scene)
        label_row.addWidget(self._vrc_add_btn)
        layout.addLayout(label_row)

        scenes_title = QLabel("Configured key scenes")
        scenes_title.setObjectName("SectionTitle")
        layout.addWidget(scenes_title)

        remove_row = QHBoxLayout()
        self._vrc_scene_picker = ScrollSafeComboBox()
        remove_row.addWidget(self._vrc_scene_picker, 1)
        self._vrc_remove_btn = PillButton("Remove", ghost=True)
        self._vrc_remove_btn.clicked.connect(self._on_vrc_remove_key_scene)
        remove_row.addWidget(self._vrc_remove_btn)
        layout.addLayout(remove_row)

        run_row = QHBoxLayout()
        run_row.addStretch(1)
        self._vrc_run_btn = PillButton("Capture && compare")
        self._vrc_run_btn.clicked.connect(self._on_vrc_run)
        run_row.addWidget(self._vrc_run_btn)
        layout.addLayout(run_row)

        self._vrc_result = QTextEdit()
        self._vrc_result.setReadOnly(True)
        self._vrc_result.setPlaceholderText("Per-scene capture/diff findings will appear here.")
        self._vrc_result.setFixedHeight(220)
        layout.addWidget(self._vrc_result)

        history_title = QLabel("Recent capture runs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._vrc_history = QTextEdit()
        self._vrc_history.setReadOnly(True)
        self._vrc_history.setFixedHeight(80)
        layout.addWidget(self._vrc_history)

    def _on_vrc_add_key_scene(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        scene_path = self._vrc_scene_path_input.text().strip()
        label = self._vrc_label_input.text().strip()
        marker_name = self._vrc_marker_input.text().strip()
        if not scene_path or not label or not marker_name:
            QMessageBox.information(
                self,
                "Missing input",
                "Scene path, label, and marker GameObject name are all required.",
            )
            return
        try:
            self._services.visual_regression_capture.add_key_scene(
                project.id, scene_path, label, marker_name
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Couldn't add key scene", str(exc))
            return
        self._vrc_scene_path_input.clear()
        self._vrc_label_input.clear()
        self._vrc_marker_input.clear()
        self._refresh_vrc_key_scenes()

    def _on_vrc_remove_key_scene(self) -> None:
        key_scene_id = self._vrc_scene_picker.currentData()
        if key_scene_id is None:
            return
        self._services.visual_regression_capture.remove_key_scene(key_scene_id)
        self._refresh_vrc_key_scenes()

    def _refresh_vrc_key_scenes(self) -> None:
        project = self._services.active_project()
        self._vrc_scene_picker.clear()
        if project is None:
            return
        for scene in self._services.visual_regression_capture.list_key_scenes(project.id):
            self._vrc_scene_picker.addItem(f"{scene.label} ({scene.scene_path})", scene.id)

    def _on_vrc_run(self) -> None:
        project = self._services.active_project()
        if project is None or not project.path:
            QMessageBox.information(
                self,
                "Pick a project first",
                "Select a project with a connected Unity folder on the Projects screen.",
            )
            return
        self._vrc_run_btn.setEnabled(False)
        self._vrc_run_btn.setText("Capturing…")
        self._vrc_result.setPlainText(
            "Launching Unity and capturing key scenes (this can take a while)…"
        )

        worker = _VisualRegressionCaptureWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_vrc_done)
        worker.failed.connect(self._on_vrc_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_vrc_done(self, finding: Finding) -> None:
        self._vrc_run_btn.setEnabled(True)
        self._vrc_run_btn.setText("Capture && compare")
        self._vrc_result.setPlainText(_format_visual_regression_capture(finding))
        self.usage_changed.emit()
        self._refresh_vrc_history()

    def _on_vrc_failed(self, message: str) -> None:
        self._vrc_run_btn.setEnabled(True)
        self._vrc_run_btn.setText("Capture && compare")
        self._vrc_result.setPlainText(message)

    def _refresh_vrc_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._vrc_history.setPlainText("Runs are saved once you select an active project.")
            return
        records = self._services.visual_regression_capture.history(project.id, limit=5)
        if not records:
            self._vrc_history.setPlainText("No capture runs saved yet.")
            return
        self._vrc_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
        )

    # --- Shader Variant & Compile Bloat Analysis (Implementation Bible, Feature 6) ---

    def _build_shader_variant_analysis(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Shader Variant & Compile Bloat Analysis")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Check for redundant shader variants bloating the build: every .shader file under "
            "this project's Assets/ is loaded in a headless Unity Editor and its compiled "
            "variant count read via UnityEditor.ShaderUtil.GetVariantCount. Estimated compile "
            "time is a rough proxy (variants x a documented per-variant estimate), not a "
            "measurement -- Spiced can't see real compiler timing."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Variant threshold:"))
        self._sva_threshold_input = QLineEdit()
        self._sva_threshold_input.setFixedWidth(70)
        self._sva_threshold_input.setPlaceholderText(str(DEFAULT_VARIANT_THRESHOLD))
        settings_row.addWidget(self._sva_threshold_input)
        self._sva_save_settings_btn = PillButton("Save as project default", ghost=True)
        self._sva_save_settings_btn.clicked.connect(self._on_sva_save_settings)
        settings_row.addWidget(self._sva_save_settings_btn)
        settings_row.addStretch(1)
        self._sva_run_btn = PillButton("Analyze shaders")
        self._sva_run_btn.clicked.connect(self._on_sva_run)
        settings_row.addWidget(self._sva_run_btn)
        layout.addLayout(settings_row)

        self._sva_result = QTextEdit()
        self._sva_result.setReadOnly(True)
        self._sva_result.setPlaceholderText("Per-shader variant findings will appear here.")
        self._sva_result.setFixedHeight(220)
        layout.addWidget(self._sva_result)

        history_title = QLabel("Recent scans")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._sva_history = QTextEdit()
        self._sva_history.setReadOnly(True)
        self._sva_history.setFixedHeight(80)
        layout.addWidget(self._sva_history)

    def _on_sva_save_settings(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        text = self._sva_threshold_input.text().strip()
        try:
            threshold = int(text) if text else None
        except ValueError:
            QMessageBox.information(
                self, "Invalid threshold", "Variant threshold must be a whole number, e.g. 100."
            )
            return
        self._services.projects.set_shader_variant_threshold(project.id, threshold)
        self.refresh()

    def _on_sva_run(self) -> None:
        project = self._services.active_project()
        if project is None or not project.path:
            QMessageBox.information(
                self,
                "Pick a project first",
                "Select a project with a connected Unity folder on the Projects screen.",
            )
            return
        self._sva_run_btn.setEnabled(False)
        self._sva_run_btn.setText("Analyzing…")
        self._sva_result.setPlainText(
            "Launching Unity and analyzing shader variants (this can take a while)…"
        )

        worker = _ShaderVariantAnalysisWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_sva_done)
        worker.failed.connect(self._on_sva_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_sva_done(self, finding: Finding) -> None:
        self._sva_run_btn.setEnabled(True)
        self._sva_run_btn.setText("Analyze shaders")
        self._sva_result.setPlainText(_format_shader_variant_analysis(finding))
        self.usage_changed.emit()
        self._refresh_sva_history()

    def _on_sva_failed(self, message: str) -> None:
        self._sva_run_btn.setEnabled(True)
        self._sva_run_btn.setText("Analyze shaders")
        self._sva_result.setPlainText(message)

    def _refresh_sva_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._sva_history.setPlainText("Runs are saved once you select an active project.")
            return
        records = self._services.shader_variant_analysis.history(project.id, limit=5)
        if not records:
            self._sva_history.setPlainText("No scans saved yet.")
            return
        self._sva_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
        )

    # --- Shader Performance Profiling -- GPU Capture (Implementation Bible, Feature 9) ---

    def _build_gpu_shader_profiling(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Shader Performance Profiling (GPU Capture)")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Flag any shaders too expensive for our low-end target: analyzes a RenderDoc capture "
            "(.rdc) you already made, aggregating real GPU time per shader and flagging any over "
            "budget for the target hardware tier. This needs RenderDoc installed separately -- "
            "Spiced never captures the frame itself (see docs for why: capturing needs a runtime "
            "hook baked into your built player, a much larger, separate mechanism this scope "
            "doesn't cover). Point this at a capture you made with RenderDoc's own UI or launcher."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        rdc_row = QHBoxLayout()
        self._gsp_rdc_input = QLineEdit()
        self._gsp_rdc_input.setPlaceholderText("Path to a .rdc capture file")
        rdc_row.addWidget(self._gsp_rdc_input, 1)
        self._gsp_rdc_browse_btn = PillButton("Browse…")
        self._gsp_rdc_browse_btn.clicked.connect(self._on_gsp_browse_rdc)
        rdc_row.addWidget(self._gsp_rdc_browse_btn)
        layout.addLayout(rdc_row)

        pymodules_row = QHBoxLayout()
        self._gsp_pymodules_input = QLineEdit()
        self._gsp_pymodules_input.setPlaceholderText("Path to RenderDoc's pymodules folder")
        pymodules_row.addWidget(self._gsp_pymodules_input, 1)
        self._gsp_pymodules_browse_btn = PillButton("Browse…")
        self._gsp_pymodules_browse_btn.clicked.connect(self._on_gsp_browse_pymodules)
        pymodules_row.addWidget(self._gsp_pymodules_browse_btn)
        layout.addLayout(pymodules_row)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Target tier:"))
        self._gsp_tier_picker = ScrollSafeComboBox()
        for tier in HARDWARE_TIERS:
            self._gsp_tier_picker.addItem(tier, tier)
        settings_row.addWidget(self._gsp_tier_picker, 1)
        self._gsp_save_settings_btn = PillButton("Save as project default", ghost=True)
        self._gsp_save_settings_btn.clicked.connect(self._on_gsp_save_settings)
        settings_row.addWidget(self._gsp_save_settings_btn)
        self._gsp_run_btn = PillButton("Analyze capture")
        self._gsp_run_btn.clicked.connect(self._on_gsp_run)
        settings_row.addWidget(self._gsp_run_btn)
        layout.addLayout(settings_row)

        self._gsp_result = QTextEdit()
        self._gsp_result.setReadOnly(True)
        self._gsp_result.setPlaceholderText("Per-shader GPU cost findings will appear here.")
        self._gsp_result.setFixedHeight(220)
        layout.addWidget(self._gsp_result)

        history_title = QLabel("Recent scans")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._gsp_history = QTextEdit()
        self._gsp_history.setReadOnly(True)
        self._gsp_history.setFixedHeight(80)
        layout.addWidget(self._gsp_history)

    def _on_gsp_browse_rdc(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a RenderDoc capture", "", "RenderDoc Captures (*.rdc)"
        )
        if path:
            self._gsp_rdc_input.setText(path)

    def _on_gsp_browse_pymodules(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick RenderDoc's pymodules folder")
        if folder:
            self._gsp_pymodules_input.setText(folder)

    def _on_gsp_save_settings(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        tier = self._gsp_tier_picker.currentData()
        self._services.projects.set_gpu_shader_profiling_settings(project.id, None, tier)
        self.refresh()

    def _on_gsp_run(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        rdc_path = self._gsp_rdc_input.text().strip()
        pymodules_path = self._gsp_pymodules_input.text().strip()
        if not rdc_path or not Path(rdc_path).is_file():
            QMessageBox.information(
                self, "Pick a capture", "Enter or browse to a .rdc capture file first."
            )
            return
        if not pymodules_path:
            QMessageBox.information(
                self, "Missing RenderDoc path", "Enter RenderDoc's pymodules folder path first."
            )
            return
        tier = self._gsp_tier_picker.currentData() or DEFAULT_HARDWARE_TIER

        self._gsp_run_btn.setEnabled(False)
        self._gsp_run_btn.setText("Analyzing…")
        self._gsp_result.setPlainText("Analyzing the capture…")

        worker = _GpuShaderProfilingWorker(self._services, project, rdc_path, pymodules_path, tier)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_gsp_done)
        worker.failed.connect(self._on_gsp_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_gsp_done(self, result: GpuProfilingRunResult) -> None:
        self._gsp_run_btn.setEnabled(True)
        self._gsp_run_btn.setText("Analyze capture")
        self._gsp_result.setPlainText(_format_gpu_shader_profiling(result.finding))
        self.usage_changed.emit()
        self._refresh_gsp_history()

    def _on_gsp_failed(self, message: str) -> None:
        self._gsp_run_btn.setEnabled(True)
        self._gsp_run_btn.setText("Analyze capture")
        self._gsp_result.setPlainText(message)

    def _refresh_gsp_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._gsp_history.setPlainText("Runs are saved once you select an active project.")
            return
        records = self._services.gpu_shader_profiling.history(project.id, limit=5)
        if not records:
            self._gsp_history.setPlainText("No scans saved yet.")
            return
        self._gsp_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
        )

    # --- Refresh --------------------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to run "
                "these scans."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")
        self._refresh_shader_history()
        self._refresh_vr_history()
        self._refresh_vrc_key_scenes()
        self._refresh_vrc_history()
        self._refresh_sva_history()
        self._refresh_gsp_history()
        if project is not None:
            if project.shader_variant_threshold is not None:
                self._sva_threshold_input.setText(str(project.shader_variant_threshold))
            if project.gpu_shader_tier:
                index = self._gsp_tier_picker.findData(project.gpu_shader_tier)
                if index >= 0:
                    self._gsp_tier_picker.setCurrentIndex(index)
