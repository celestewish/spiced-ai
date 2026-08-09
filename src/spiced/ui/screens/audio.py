"""Audio: Audio Implementation Checklist, Mix/Level QA, Localization Audio Sync.

Three sections, all local/deterministic -- no AI provider is used anywhere
on this screen. Recursive scans run on a worker thread (via
``ui.thread_utils.launch_worker``) for UI responsiveness even though none of
them involve an AI call, the same pattern the Asset Optimization Sweep and
Localization Readiness scans already use.
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
