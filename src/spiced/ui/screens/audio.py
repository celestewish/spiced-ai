"""Audio: Audio Implementation Checklist, Mix/Level QA, Localization Audio
Sync, Batch Loudness Normalization.

The first three sections are local/deterministic -- no AI provider is used
anywhere on this screen. Recursive scans run on a worker thread (via
``ui.thread_utils.launch_worker``) for UI responsiveness even though none of
them involve an AI call, the same pattern the Asset Optimization Sweep and
Localization Readiness scans already use.

Batch Loudness Normalization (SPICED_IMPLEMENTATION_BIBLE.md, Feature 1) is
the first section on the Bible's separate automation track: it drives a
real external tool (ffmpeg, via ``automation.loudness_normalize``) rather
than only reading project files, and its results are the shared ``Finding``
schema instead of a feature-specific report shape -- everything else about
how it's wired into this screen (worker thread, run button, result panel,
saved-run history) still matches the sections above.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QFileDialog,
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
from spiced.automation.finding import Finding
from spiced.automation.loudness_normalize import DEFAULT_TARGET_LUFS, FfmpegNotAvailableError
from spiced.automation.mix_technical_qa import DEFAULT_SILENCE_MS
from spiced.core.audio_implementation_checklist import AudioImplementationScan
from spiced.core.audio_implementation_checklist import NoUnityFolderError as AudioNoUnityFolderError
from spiced.core.localization_audio_sync import (
    STALENESS_CAVEAT,
    LocalizationAudioSyncResult,
    parse_script_lines,
    scan_localization_audio_sync,
    scan_voice_folder,
)
from spiced.core.mix_level_qa import WAV_ONLY_CAVEAT, MixQaBatchResult
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.tool_switcher import build_tool_switcher


class _AudioChecklistWorker(QObject):
    done = Signal(object)  # AudioImplementationScan
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            scan, _report = self._services.audio_implementation_checklist.scan(self._project)
            self._services.record_telemetry_event("audio.implementation_checklist_run")
            self.done.emit(scan)
        except AudioNoUnityFolderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while scanning: {exc}")


class _SendToTeamBoardWorker(QObject):
    done = Signal(object)  # TeamTask | None
    failed = Signal(str)

    def __init__(self, services: Services, project_uuid: str, title: str, description: str,
                 source_ref: str) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid
        self._title = title
        self._description = description
        self._source_ref = source_ref

    def run(self) -> None:
        try:
            task = self._services.teams.send_finding_to_team_board(
                self._project_uuid, self._title,
                description=self._description,
                assigned_discipline="audio",
                source_type="audio",
                source_ref=self._source_ref,
            )
            self.done.emit(task)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't send to the Team board: {exc}")


def _audio_checklist_gap_count(scan: AudioImplementationScan) -> int:
    return len(scan.unmatched_references) + len(scan.unreferenced_audio_files)


def _audio_checklist_source_ref(scan: AudioImplementationScan) -> str | None:
    if scan.unmatched_references:
        r = scan.unmatched_references[0]
        return f"unmatched-audio-ref:{r.file}:{r.line}"
    if scan.unreferenced_audio_files:
        return f"unreferenced-audio-file:{scan.unreferenced_audio_files[0]}"
    return None


class _MixQaWorker(QObject):
    done = Signal(object)  # MixQaBatchResult
    failed = Signal(str)

    def __init__(self, services: Services, folder: str, project) -> None:
        super().__init__()
        self._services = services
        self._folder = folder
        self._project = project

    def run(self) -> None:
        try:
            result, _report = self._services.mix_level_qa.scan_folder(
                self._folder, project=self._project
            )
            self._services.record_telemetry_event("audio.mix_level_qa_run")
            self.done.emit(result)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while analyzing WAV files: {exc}")


class _LocalizationAudioSyncWorker(QObject):
    done = Signal(object)  # LocalizationAudioSyncResult
    failed = Signal(str)

    def __init__(self, services: Services, script_text: str, voice_folder: str) -> None:
        super().__init__()
        self._services = services
        self._script_text = script_text
        self._voice_folder = voice_folder

    def run(self) -> None:
        try:
            script_lines = parse_script_lines(self._script_text, time.time())
            voice_files = scan_voice_folder(self._voice_folder)
            result = scan_localization_audio_sync(script_lines, voice_files)
            self._services.record_telemetry_event("audio.localization_audio_sync_run")
            self.done.emit(result)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while checking sync: {exc}")


class _LoudnessNormalizeWorker(QObject):
    done = Signal(object)  # Finding
    failed = Signal(str)

    def __init__(
        self, services: Services, folder: str, project, target_lufs: float
    ) -> None:
        super().__init__()
        self._services = services
        self._folder = folder
        self._project = project
        self._target_lufs = target_lufs

    def run(self) -> None:
        try:
            finding, _record = self._services.loudness_normalize.normalize(
                self._project, self._folder, target_lufs=self._target_lufs
            )
            self._services.record_telemetry_event("audio.loudness_normalize_run")
            self.done.emit(finding)
        except FfmpegNotAvailableError as exc:
            self.failed.emit(
                f"ffmpeg isn't available on this machine: {exc}\n"
                "See docs/loudness_normalize_ffmpeg.md for install instructions."
            )
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while normalizing audio: {exc}")


class _MixTechnicalQaWorker(QObject):
    done = Signal(object)  # Finding
    failed = Signal(str)

    def __init__(self, services: Services, folder: str, project) -> None:
        super().__init__()
        self._services = services
        self._folder = folder
        self._project = project

    def run(self) -> None:
        try:
            finding, _record = self._services.mix_technical_qa.scan(self._project, self._folder)
            self._services.record_telemetry_event("audio.mix_technical_qa_run")
            self.done.emit(finding)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while checking audio files: {exc}")


def _format_mix_technical_qa(finding: Finding) -> str:
    lines = [finding.summary, ""]
    if not finding.items:
        lines.append("No WAV files were checked.")
        return "\n".join(lines)
    for item in finding.items:
        lines.append(f"- [{item.severity}] {item.message}")
        for region in item.detail.get("clipping_regions", []):
            lines.append(f"    · clipping: {region['start_ms']}ms - {region['end_ms']}ms")
        for region in item.detail.get("silence_regions", []):
            lines.append(f"    · silence: {region['start_ms']}ms - {region['end_ms']}ms")
    return "\n".join(lines)


def _format_audio_checklist(scan: AudioImplementationScan) -> str:
    lines = [scan.caveat, ""]
    lines.append(
        f"{scan.scripts_scanned} script(s) scanned, {scan.audio_files_found} audio file(s) found."
    )
    lines.append("")
    lines.append(f"Matched references: {len(scan.matched_references)}")
    lines.append(
        "Unmatched script references (variable named like a clip, no matching audio file found):"
    )
    if scan.unmatched_references:
        for r in scan.unmatched_references[:30]:
            lines.append(f"- {r.file}:{r.line} `{r.variable_name}` ({r.call_kind})")
    else:
        lines.append("None found.")
    lines.append("")
    lines.append("Audio files not obviously referenced anywhere scanned:")
    if scan.unreferenced_audio_files:
        for f in scan.unreferenced_audio_files[:30]:
            lines.append(f"- {f}")
    else:
        lines.append("None found.")
    return "\n".join(lines)


def _format_mix_qa(result: MixQaBatchResult) -> str:
    lines = [result.caveat, ""]
    if not result.files and not result.unreadable:
        lines.append("No WAV files found in that folder.")
        return "\n".join(lines)
    for f in result.files:
        flags = []
        if f.clipping_risk:
            flags.append("possible clipping")
        if f.silence_gaps:
            flags.append(f"{len(f.silence_gaps)} silence gap(s)")
        if f.path in result.loudness_outliers:
            flags.append("relative loudness outlier")
        flag_text = ", ".join(flags) if flags else "no flags"
        lines.append(
            f"- {Path(f.path).name}: peak {f.peak_ratio:.2f}, rms {f.rms_ratio:.2f}, "
            f"{f.duration_seconds:.1f}s ({flag_text})"
        )
    if result.unreadable:
        lines.append("")
        lines.append("Couldn't analyze:")
        for path, error in result.unreadable:
            lines.append(f"- {Path(path).name}: {error}")
    return "\n".join(lines)


def _format_localization_audio_sync(result: LocalizationAudioSyncResult) -> str:
    lines = [result.caveat, ""]
    lines.append(f"{result.script_lines_checked} script line(s) checked.")
    lines.append("")
    lines.append("Possibly stale recordings (audio older than the script line's last edit):")
    if result.stale_recordings:
        for s in result.stale_recordings:
            lines.append(f"- {s.line_id}: {Path(s.audio_path).name}")
    else:
        lines.append("None found.")
    lines.append("")
    lines.append("Script lines with no matching audio file:")
    if result.missing_audio:
        for m in result.missing_audio:
            lines.append(f"- {m.line_id}: \"{m.script_text_excerpt}\"")
    else:
        lines.append("None found.")
    if result.unmatched_audio_files:
        lines.append("")
        lines.append(
            "Audio files with no inferable line ID (filename didn't match the convention):"
        )
        for path in result.unmatched_audio_files:
            lines.append(f"- {Path(path).name}")
    return "\n".join(lines)


def _format_loudness_normalize(finding: Finding) -> str:
    lines = [finding.summary, ""]
    if not finding.items:
        lines.append("No audio files were processed.")
        return "\n".join(lines)
    for item in finding.items:
        lines.append(f"- [{item.severity}] {item.message}")
    return "\n".join(lines)


class AudioScreen(QWidget):
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
        layout.setSpacing(12)

        title = QLabel("Audio")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        columns, self._stack, self._tool_group = build_tool_switcher(
            self,
            [
                ("Audio Implementation Checklist", self._build_audio_checklist),
                ("Mix/Level QA", self._build_mix_qa),
                ("Localization Audio Sync", self._build_localization_audio_sync),
                ("Batch Loudness Normalization", self._build_loudness_normalize),
                ("Mix Technical QA", self._build_mix_technical_qa),
            ],
        )
        layout.addLayout(columns, 1)

        self.refresh()

    # --- Audio Implementation Checklist -------------------------------------

    def _build_audio_checklist(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Audio Implementation Checklist")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Scans this project's .cs scripts for audio-triggering code (AudioSource.Play, "
            "PlayOneShot, .clip assignments) and cross-references the clip variable/field names "
            "against audio assets under Assets/, by name similarity. Best-effort only -- audio "
            "assigned purely via the Inspector, or loaded dynamically, won't be seen."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        row.addStretch(1)
        self._audio_checklist_run_btn = PillButton("Run checklist")
        self._audio_checklist_run_btn.clicked.connect(self._on_audio_checklist_run)
        row.addWidget(self._audio_checklist_run_btn)
        layout.addLayout(row)

        self._audio_checklist_result = QTextEdit()
        self._audio_checklist_result.setReadOnly(True)
        self._audio_checklist_result.setPlaceholderText("Checklist findings will appear here.")
        self._audio_checklist_result.setFixedHeight(220)
        layout.addWidget(self._audio_checklist_result)

        # "Send to Team Board" routing entry point (Phase J, #3): only
        # enabled once a scan has gaps AND the active project is
        # team-linked -- creates a TeamTask pre-filled with discipline
        # "audio" and a source_ref back to the first flagged gap.
        team_board_row = QHBoxLayout()
        team_board_row.addStretch(1)
        self._audio_send_btn = PillButton("Send to Team Board", ghost=True)
        self._audio_send_btn.setEnabled(False)
        self._audio_send_btn.clicked.connect(self._on_send_audio_gaps_to_team_board)
        team_board_row.addWidget(self._audio_send_btn)
        layout.addLayout(team_board_row)
        self._audio_send_status = QLabel("")
        self._audio_send_status.setObjectName("Muted")
        self._audio_send_status.setWordWrap(True)
        layout.addWidget(self._audio_send_status)
        self._last_audio_checklist_scan: AudioImplementationScan | None = None

        history_title = QLabel("Recent checklist runs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._audio_checklist_history = QTextEdit()
        self._audio_checklist_history.setReadOnly(True)
        self._audio_checklist_history.setFixedHeight(80)
        layout.addWidget(self._audio_checklist_history)

    def _on_audio_checklist_run(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._audio_checklist_run_btn.setEnabled(False)
        self._audio_checklist_run_btn.setText("Scanning…")
        self._audio_checklist_result.setPlainText("Scanning scripts and audio assets…")

        worker = _AudioChecklistWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_audio_checklist_done)
        worker.failed.connect(self._on_audio_checklist_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_audio_checklist_done(self, scan: AudioImplementationScan) -> None:
        self._audio_checklist_run_btn.setEnabled(True)
        self._audio_checklist_run_btn.setText("Run checklist")
        self._audio_checklist_result.setPlainText(_format_audio_checklist(scan))
        self._last_audio_checklist_scan = scan
        project = self._services.active_project()
        team_linked = bool(project and project.project_uuid)
        self._audio_send_btn.setEnabled(bool(_audio_checklist_gap_count(scan)) and team_linked)
        self._audio_send_status.setText(
            "" if team_linked else
            "Link this project to a team (Projects screen) to send findings to a Team Board."
        )
        self.usage_changed.emit()
        self._refresh_audio_checklist_history()

    def _on_audio_checklist_failed(self, message: str) -> None:
        self._audio_checklist_run_btn.setEnabled(True)
        self._audio_checklist_run_btn.setText("Run checklist")
        self._audio_checklist_result.setPlainText(message)

    def _on_send_audio_gaps_to_team_board(self) -> None:
        project = self._services.active_project()
        if project is None or not project.project_uuid or self._last_audio_checklist_scan is None:
            return
        scan = self._last_audio_checklist_scan
        gap_count = _audio_checklist_gap_count(scan)
        title = f"Audio Implementation Checklist: {gap_count} gap(s) in {project.name}"
        source_ref = _audio_checklist_source_ref(scan)
        self._audio_send_btn.setEnabled(False)
        self._audio_send_status.setText("Sending…")

        worker = _SendToTeamBoardWorker(
            self._services, project.project_uuid, title, _format_audio_checklist(scan),
            source_ref or "audio-implementation-checklist",
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_audio_gaps_sent)
        worker.failed.connect(self._on_audio_gaps_send_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_audio_gaps_sent(self, task) -> None:
        self._audio_send_btn.setEnabled(True)
        self._audio_send_status.setText(
            "Sent to the Team board." if task is not None
            else "This project isn't linked to a team."
        )

    def _on_audio_gaps_send_failed(self, message: str) -> None:
        self._audio_send_btn.setEnabled(True)
        self._audio_send_status.setText(message)

    def _refresh_audio_checklist_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._audio_checklist_history.setPlainText(
                "Runs are saved once you select an active project."
            )
            return
        reports = self._services.audio_implementation_checklist.history(project.id, limit=5)
        if not reports:
            self._audio_checklist_history.setPlainText("No checklist runs saved yet.")
            return
        lines = [
            f"[{r.created_at}] {r.findings.get('scripts_scanned', 0)} script(s) scanned"
            for r in reports
        ]
        self._audio_checklist_history.setPlainText("\n".join(lines))

    # --- Mix/Level QA ---------------------------------------------------------

    def _build_mix_qa(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Mix QA")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(WAV_ONLY_CAVEAT)
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._mix_folder_input = QLineEdit()
        self._mix_folder_input.setPlaceholderText("Folder to scan for .wav files")
        row.addWidget(self._mix_folder_input, 1)
        self._mix_browse_btn = PillButton("Browse…")
        self._mix_browse_btn.clicked.connect(self._on_mix_browse)
        row.addWidget(self._mix_browse_btn)
        self._mix_run_btn = PillButton("Run Mix QA")
        self._mix_run_btn.clicked.connect(self._on_mix_run)
        row.addWidget(self._mix_run_btn)
        layout.addLayout(row)

        self._mix_result = QTextEdit()
        self._mix_result.setReadOnly(True)
        self._mix_result.setPlaceholderText("Peak/RMS/clipping/silence findings will appear here.")
        self._mix_result.setFixedHeight(200)
        layout.addWidget(self._mix_result)

    def _on_mix_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick a folder of WAV files")
        if folder:
            self._mix_folder_input.setText(folder)

    def _on_mix_run(self) -> None:
        folder = self._mix_folder_input.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.information(
                self, "Pick a folder", "Enter or browse to a folder containing .wav files first."
            )
            return
        self._mix_run_btn.setEnabled(False)
        self._mix_run_btn.setText("Analyzing…")
        self._mix_result.setPlainText("Analyzing WAV files…")

        worker = _MixQaWorker(self._services, folder, self._services.active_project())
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_mix_done)
        worker.failed.connect(self._on_mix_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_mix_done(self, result: MixQaBatchResult) -> None:
        self._mix_run_btn.setEnabled(True)
        self._mix_run_btn.setText("Run Mix QA")
        self._mix_result.setPlainText(_format_mix_qa(result))
        self.usage_changed.emit()

    def _on_mix_failed(self, message: str) -> None:
        self._mix_run_btn.setEnabled(True)
        self._mix_run_btn.setText("Run Mix QA")
        self._mix_result.setPlainText(message)

    # --- Localization Audio Sync -----------------------------------------------

    def _build_localization_audio_sync(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Localization Audio Sync")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Paired with the Localization Readiness Check (Debugging Buddy screen) rather than "
            "duplicating it here. " + STALENESS_CAVEAT
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._loc_script_input = QPlainTextEdit()
        self._loc_script_input.setPlaceholderText(
            "One script line per row, as: line_id,text\n"
            "e.g.\nline001,Welcome to the dungeon, traveler!\nline002,Watch out for traps."
        )
        self._loc_script_input.setFixedHeight(100)
        layout.addWidget(self._loc_script_input)

        row = QHBoxLayout()
        self._loc_folder_input = QLineEdit()
        self._loc_folder_input.setPlaceholderText("Folder of voice-line audio files")
        row.addWidget(self._loc_folder_input, 1)
        self._loc_browse_btn = PillButton("Browse…")
        self._loc_browse_btn.clicked.connect(self._on_loc_browse)
        row.addWidget(self._loc_browse_btn)
        self._loc_run_btn = PillButton("Check sync")
        self._loc_run_btn.clicked.connect(self._on_loc_run)
        row.addWidget(self._loc_run_btn)
        layout.addLayout(row)

        self._loc_result = QTextEdit()
        self._loc_result.setReadOnly(True)
        self._loc_result.setPlaceholderText("Staleness/coverage findings will appear here.")
        self._loc_result.setFixedHeight(180)
        layout.addWidget(self._loc_result)

    def _on_loc_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick a folder of voice-line audio")
        if folder:
            self._loc_folder_input.setText(folder)

    def _on_loc_run(self) -> None:
        script_text = self._loc_script_input.toPlainText().strip()
        folder = self._loc_folder_input.text().strip()
        if not script_text or not folder:
            QMessageBox.information(
                self, "Missing input", "Paste script lines and pick a voice-line folder first."
            )
            return
        self._loc_run_btn.setEnabled(False)
        self._loc_run_btn.setText("Checking…")
        self._loc_result.setPlainText("Checking script/audio sync…")

        worker = _LocalizationAudioSyncWorker(self._services, script_text, folder)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_loc_done)
        worker.failed.connect(self._on_loc_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_loc_done(self, result: LocalizationAudioSyncResult) -> None:
        self._loc_run_btn.setEnabled(True)
        self._loc_run_btn.setText("Check sync")
        self._loc_result.setPlainText(_format_localization_audio_sync(result))

    def _on_loc_failed(self, message: str) -> None:
        self._loc_run_btn.setEnabled(True)
        self._loc_run_btn.setText("Check sync")
        self._loc_result.setPlainText(message)

    # --- Batch Loudness Normalization (Implementation Bible, Feature 1) ------

    def _build_loudness_normalize(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Batch Loudness Normalization")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Batch normalize and trim all new SFX files to spec: every .wav/.mp3/.ogg file in "
            "the folder is brought to a consistent EBU R128 loudness target via ffmpeg, so devs "
            "stop shipping inconsistent volume levels. Output goes to a sibling "
            "'<folder>_normalized' folder -- source files are never modified. Requires ffmpeg "
            "installed on this machine (see docs/loudness_normalize_ffmpeg.md)."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._loudness_folder_input = QLineEdit()
        self._loudness_folder_input.setPlaceholderText("Folder of audio files to normalize")
        row.addWidget(self._loudness_folder_input, 1)
        self._loudness_browse_btn = PillButton("Browse…")
        self._loudness_browse_btn.clicked.connect(self._on_loudness_browse)
        row.addWidget(self._loudness_browse_btn)
        layout.addLayout(row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target LUFS:"))
        self._loudness_target_input = QLineEdit()
        self._loudness_target_input.setFixedWidth(80)
        self._loudness_target_input.setPlaceholderText(str(DEFAULT_TARGET_LUFS))
        target_row.addWidget(self._loudness_target_input)
        self._loudness_save_target_btn = PillButton("Save as project default", ghost=True)
        self._loudness_save_target_btn.clicked.connect(self._on_loudness_save_target)
        target_row.addWidget(self._loudness_save_target_btn)
        target_row.addStretch(1)
        self._loudness_run_btn = PillButton("Normalize folder")
        self._loudness_run_btn.clicked.connect(self._on_loudness_run)
        target_row.addWidget(self._loudness_run_btn)
        layout.addLayout(target_row)

        self._loudness_result = QTextEdit()
        self._loudness_result.setReadOnly(True)
        self._loudness_result.setPlaceholderText(
            "Per-file before/after loudness will appear here."
        )
        self._loudness_result.setFixedHeight(220)
        layout.addWidget(self._loudness_result)

        history_title = QLabel("Recent normalization runs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._loudness_history = QTextEdit()
        self._loudness_history.setReadOnly(True)
        self._loudness_history.setFixedHeight(80)
        layout.addWidget(self._loudness_history)

    def _on_loudness_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick a folder of audio files")
        if folder:
            self._loudness_folder_input.setText(folder)

    def _loudness_target_from_field(self) -> float | None:
        """Parse the target-LUFS field; None (fall back to the project's saved
        setting/default) for blank input, raises ValueError for bad input."""
        text = self._loudness_target_input.text().strip()
        return float(text) if text else None

    def _on_loudness_run(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        folder = self._loudness_folder_input.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.information(
                self, "Pick a folder", "Enter or browse to a folder containing audio files first."
            )
            return
        try:
            target_lufs = self._loudness_target_from_field()
        except ValueError:
            QMessageBox.information(
                self, "Invalid target", "Target LUFS must be a number, e.g. -23."
            )
            return

        self._loudness_run_btn.setEnabled(False)
        self._loudness_run_btn.setText("Normalizing…")
        self._loudness_result.setPlainText("Normalizing audio files…")

        worker = _LoudnessNormalizeWorker(self._services, folder, project, target_lufs)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_loudness_done)
        worker.failed.connect(self._on_loudness_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_loudness_done(self, finding: Finding) -> None:
        self._loudness_run_btn.setEnabled(True)
        self._loudness_run_btn.setText("Normalize folder")
        self._loudness_result.setPlainText(_format_loudness_normalize(finding))
        self.usage_changed.emit()
        self._refresh_loudness_history()

    def _on_loudness_failed(self, message: str) -> None:
        self._loudness_run_btn.setEnabled(True)
        self._loudness_run_btn.setText("Normalize folder")
        self._loudness_result.setPlainText(message)

    def _on_loudness_save_target(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        try:
            target_lufs = self._loudness_target_from_field()
        except ValueError:
            QMessageBox.information(
                self, "Invalid target", "Target LUFS must be a number, e.g. -23."
            )
            return
        self._services.projects.set_loudness_normalize_target(project.id, target_lufs)
        self.refresh()

    def _refresh_loudness_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._loudness_history.setPlainText(
                "Runs are saved once you select an active project."
            )
            return
        records = self._services.loudness_normalize.history(project.id, limit=5)
        if not records:
            self._loudness_history.setPlainText("No normalization runs saved yet.")
            return
        self._loudness_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
        )

    # --- Mix Technical QA (Implementation Bible, Feature 5) -------------------

    def _build_mix_technical_qa(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Mix Technical QA")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Scan the audio library for clipping or volume inconsistencies: every .wav file is "
            "checked for clipping (samples pinned near full scale for more than a few samples) "
            "and unexpected silence gaps mid-file, with timestamps. WAV only -- see the Mix/Level "
            "QA section above for why compressed formats aren't analyzed."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._mtq_folder_input = QLineEdit()
        self._mtq_folder_input.setPlaceholderText("Folder to scan for .wav files")
        row.addWidget(self._mtq_folder_input, 1)
        self._mtq_browse_btn = PillButton("Browse…")
        self._mtq_browse_btn.clicked.connect(self._on_mtq_browse)
        row.addWidget(self._mtq_browse_btn)
        layout.addLayout(row)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Min. silence (ms):"))
        self._mtq_silence_input = QLineEdit()
        self._mtq_silence_input.setFixedWidth(70)
        self._mtq_silence_input.setPlaceholderText(str(DEFAULT_SILENCE_MS))
        settings_row.addWidget(self._mtq_silence_input)
        self._mtq_save_settings_btn = PillButton("Save as project default", ghost=True)
        self._mtq_save_settings_btn.clicked.connect(self._on_mtq_save_settings)
        settings_row.addWidget(self._mtq_save_settings_btn)
        settings_row.addStretch(1)
        self._mtq_run_btn = PillButton("Check audio")
        self._mtq_run_btn.clicked.connect(self._on_mtq_run)
        settings_row.addWidget(self._mtq_run_btn)
        layout.addLayout(settings_row)

        self._mtq_result = QTextEdit()
        self._mtq_result.setReadOnly(True)
        self._mtq_result.setPlaceholderText("Clipping/silence findings will appear here.")
        self._mtq_result.setFixedHeight(220)
        layout.addWidget(self._mtq_result)

        history_title = QLabel("Recent checks")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._mtq_history = QTextEdit()
        self._mtq_history.setReadOnly(True)
        self._mtq_history.setFixedHeight(80)
        layout.addWidget(self._mtq_history)

    def _on_mtq_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pick a folder of WAV files")
        if folder:
            self._mtq_folder_input.setText(folder)

    def _on_mtq_save_settings(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        text = self._mtq_silence_input.text().strip()
        try:
            silence_ms = float(text) if text else None
        except ValueError:
            QMessageBox.information(
                self, "Invalid value", "Minimum silence must be a number of milliseconds, e.g. 300."
            )
            return
        self._services.projects.set_mix_qa_silence_ms(project.id, silence_ms)
        self.refresh()

    def _on_mtq_run(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        folder = self._mtq_folder_input.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.information(
                self, "Pick a folder", "Enter or browse to a folder containing .wav files first."
            )
            return
        self._mtq_run_btn.setEnabled(False)
        self._mtq_run_btn.setText("Checking…")
        self._mtq_result.setPlainText("Checking audio files…")

        worker = _MixTechnicalQaWorker(self._services, folder, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_mtq_done)
        worker.failed.connect(self._on_mtq_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_mtq_done(self, finding: Finding) -> None:
        self._mtq_run_btn.setEnabled(True)
        self._mtq_run_btn.setText("Check audio")
        self._mtq_result.setPlainText(_format_mix_technical_qa(finding))
        self.usage_changed.emit()
        self._refresh_mtq_history()

    def _on_mtq_failed(self, message: str) -> None:
        self._mtq_run_btn.setEnabled(True)
        self._mtq_run_btn.setText("Check audio")
        self._mtq_result.setPlainText(message)

    def _refresh_mtq_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._mtq_history.setPlainText("Runs are saved once you select an active project.")
            return
        records = self._services.mix_technical_qa.history(project.id, limit=5)
        if not records:
            self._mtq_history.setPlainText("No checks saved yet.")
            return
        self._mtq_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
        )

    # --- Refresh -----------------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to run "
                "the checklist and save runs."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")
        self._refresh_audio_checklist_history()
        self._refresh_loudness_history()
        self._refresh_mtq_history()
        if project is not None:
            if project.loudness_normalize_target_lufs is not None:
                self._loudness_target_input.setText(str(project.loudness_normalize_target_lufs))
            if project.mix_qa_silence_ms is not None:
                self._mtq_silence_input.setText(str(project.mix_qa_silence_ms))
