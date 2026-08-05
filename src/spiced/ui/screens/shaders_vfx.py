"""Shaders/VFX: Shader Performance Profiling, Visual Regression Testing.

New sidebar page (Phase J, section 8 part 2). Both sections are local,
deterministic scans -- no AI provider is used anywhere on this screen, the
same discipline as the Art/Audio/Animation screens (Phase I). Scans run on a
worker thread via ``ui.thread_utils.launch_worker`` for UI responsiveness,
same as every other recursive/batch scan in this codebase.
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
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.shader_performance_profiling import (
    NoUnityFolderError as ShaderNoUnityFolderError,
)
from spiced.core.shader_performance_profiling import ShaderProfilingResult
from spiced.core.visual_regression import UnreadableImageError, VisualRegressionResult
from spiced.ui.thread_utils import launch_worker


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

        title = QLabel("Shaders/VFX")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        self._build_shader_profiling(layout)
        self._build_visual_regression(layout)

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
        self._shader_run_btn = QPushButton("Scan shaders")
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
        before_browse = QPushButton("Browse…")
        before_browse.clicked.connect(self._on_browse_before)
        before_row.addWidget(before_browse)
        layout.addLayout(before_row)

        after_row = QHBoxLayout()
        after_row.addWidget(QLabel("After folder:"))
        self._after_input = QLineEdit()
        self._after_input.setPlaceholderText("Screenshots from the newer build")
        after_row.addWidget(self._after_input, 1)
        after_browse = QPushButton("Browse…")
        after_browse.clicked.connect(self._on_browse_after)
        after_row.addWidget(after_browse)
        layout.addLayout(after_row)

        run_row = QHBoxLayout()
        run_row.addStretch(1)
        self._vr_run_btn = QPushButton("Diff screenshots")
        self._vr_run_btn.clicked.connect(self._on_vr_run)
        run_row.addWidget(self._vr_run_btn)
        layout.addLayout(run_row)

        self._vr_result = QTextEdit()
        self._vr_result.setReadOnly(True)
        self._vr_result.setPlaceholderText("Visual diff findings will appear here.")
        self._vr_result.setFixedHeight(240)
        layout.addWidget(self._vr_result)

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

    def _on_vr_failed(self, message: str) -> None:
        self._vr_run_btn.setEnabled(True)
        self._vr_run_btn.setText("Diff screenshots")
        self._vr_result.setPlainText(message)

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
