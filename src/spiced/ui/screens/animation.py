"""Animation: Animation Bug Detection, State Machine Health.

Two sections, both static analysis of ``.controller`` files via
``connectors.unity_controller_scan`` -- no AI provider is used anywhere on
this screen. Animation Bug Detection surfaces *risk indicators*, never
confirmed bugs; State Machine Sanity Check surfaces genuine structural
problems (unreachable states, missing transition targets). Both scans run
on a worker thread for UI responsiveness even though neither calls an AI
provider.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.animation_bug_detection import AnimationBugScanResult, detect_animation_bugs
from spiced.core.animation_state_machine_check import NoUnityFolderError, StateMachineScanResult
from spiced.ui.thread_utils import launch_worker


class _AnimationBugWorker(QObject):
    done = Signal(object)  # AnimationBugScanResult
    failed = Signal(str)

    def __init__(self, services: Services, project_path: str) -> None:
        super().__init__()
        self._services = services
        self._project_path = project_path

    def run(self) -> None:
        try:
            result = detect_animation_bugs(self._project_path)
            self._services.record_telemetry_event("animation.bug_detection_run")
            self.done.emit(result)
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
                assigned_discipline="animation",
                source_type="animation",
                source_ref=self._source_ref,
            )
            self.done.emit(task)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't send to the Team board: {exc}")


def _animation_bug_source_ref(result: AnimationBugScanResult) -> str | None:
    """A stable reference back to the first flagged finding -- matches the
    'known_issue signature or feedback_task id' traceability spec calls for,
    adapted to a finding kind with no persisted id of its own."""
    if result.empty_states:
        f = result.empty_states[0]
        return f"empty-state:{f.controller_file}:{f.state_file_id}"
    if result.zero_duration_transitions:
        f = result.zero_duration_transitions[0]
        return f"zero-duration-transition:{f.controller_file}:{f.transition_file_id}"
    return None


class _StateMachineCheckWorker(QObject):
    done = Signal(object)  # StateMachineScanResult
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            result, _report = self._services.animation_state_machine_check.scan(self._project)
            self._services.record_telemetry_event("animation.state_machine_check_run")
            self.done.emit(result)
        except NoUnityFolderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while scanning: {exc}")


def _format_bug_scan(result: AnimationBugScanResult) -> str:
    lines = [result.caveat, ""]
    lines.append(f"{result.controllers_scanned} Animator Controller file(s) scanned.")
    lines.append("")
    lines.append("States with no motion assigned (T-posing risk):")
    if result.empty_states:
        for f in result.empty_states:
            lines.append(f"- {f.controller_file}: state \"{f.state_name or f.state_file_id}\"")
    else:
        lines.append("None found.")
    lines.append("")
    lines.append("Zero-duration transitions (possible visible snap):")
    if result.zero_duration_transitions:
        for f in result.zero_duration_transitions:
            frm = f.from_state_name or "(unknown source)"
            to = f.to_state_name or "(unknown target)"
            lines.append(f"- {f.controller_file}: {frm} -> {to}")
    else:
        lines.append("None found.")
    return "\n".join(lines)


def _format_state_machine_scan(result: StateMachineScanResult) -> str:
    lines = [result.caveat, ""]
    lines.append(f"{result.controllers_scanned} Animator Controller file(s) scanned.")
    lines.append("")
    lines.append("Unreachable states:")
    if result.unreachable_states:
        for f in result.unreachable_states:
            lines.append(f"- {f.controller_file}: state \"{f.state_name or f.state_file_id}\"")
    else:
        lines.append("None found.")
    lines.append("")
    lines.append("Transitions pointing to a missing target:")
    if result.missing_targets:
        for f in result.missing_targets:
            lines.append(
                f"- {f.controller_file}: transition {f.transition_file_id} -> missing "
                f"{f.missing_kind} {f.missing_file_id}"
            )
    else:
        lines.append("None found.")
    return "\n".join(lines)


class AnimationScreen(QWidget):
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
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("Animation")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        self._build_bug_detection(layout)
        self._build_state_machine_check(layout)

        self.refresh()

    # --- Animation Bug Detection ---------------------------------------------

    def _build_bug_detection(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Animation Bug Detection")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Parses this project's Animator Controller (.controller) files for structural RISK "
            "INDICATORS -- never confirmed bugs, since Spiced never runs your game and cannot "
            "observe actual T-posing, foot-sliding, or a visible snap. Flags states with no "
            "motion assigned and zero-duration transitions. See the results for the full caveat."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        row.addStretch(1)
        self._bug_run_btn = QPushButton("Scan for risk indicators")
        self._bug_run_btn.clicked.connect(self._on_bug_scan_run)
        row.addWidget(self._bug_run_btn)
        layout.addLayout(row)

        self._bug_result = QTextEdit()
        self._bug_result.setReadOnly(True)
        self._bug_result.setPlaceholderText("Risk indicators will appear here.")
        self._bug_result.setFixedHeight(220)
        layout.addWidget(self._bug_result)

        # "Send to Team Board" routing entry point (Phase J, #3): only
        # enabled once a scan has findings AND the active project is
        # team-linked -- creates a TeamTask pre-filled with discipline
        # "animation" and a source_ref back to the first flagged finding.
        team_board_row = QHBoxLayout()
        team_board_row.addStretch(1)
        self._bug_send_btn = QPushButton("Send to Team Board")
        self._bug_send_btn.setObjectName("Ghost")
        self._bug_send_btn.setEnabled(False)
        self._bug_send_btn.clicked.connect(self._on_send_bug_findings_to_team_board)
        team_board_row.addWidget(self._bug_send_btn)
        layout.addLayout(team_board_row)
        self._bug_send_status = QLabel("")
        self._bug_send_status.setObjectName("Muted")
        self._bug_send_status.setWordWrap(True)
        layout.addWidget(self._bug_send_status)
        self._last_bug_scan: AnimationBugScanResult | None = None

    def _on_bug_scan_run(self) -> None:
        project = self._services.active_project()
        if project is None or not project.path:
            QMessageBox.information(
                self, "Pick a project first",
                "Select a project with a connected Unity folder on the Projects screen.",
            )
            return
        self._bug_run_btn.setEnabled(False)
        self._bug_run_btn.setText("Scanning…")
        self._bug_result.setPlainText("Scanning Animator Controller files…")

        worker = _AnimationBugWorker(self._services, project.path)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_bug_scan_done)
        worker.failed.connect(self._on_bug_scan_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_bug_scan_done(self, result: AnimationBugScanResult) -> None:
        self._bug_run_btn.setEnabled(True)
        self._bug_run_btn.setText("Scan for risk indicators")
        self._bug_result.setPlainText(_format_bug_scan(result))
        self._last_bug_scan = result
        project = self._services.active_project()
        team_linked = bool(project and project.project_uuid)
        self._bug_send_btn.setEnabled(bool(result.flagged_count) and team_linked)
        self._bug_send_status.setText(
            "" if team_linked else
            "Link this project to a team (Projects screen) to send findings to a Team Board."
        )
        self.usage_changed.emit()

    def _on_bug_scan_failed(self, message: str) -> None:
        self._bug_run_btn.setEnabled(True)
        self._bug_run_btn.setText("Scan for risk indicators")
        self._bug_result.setPlainText(message)

    def _on_send_bug_findings_to_team_board(self) -> None:
        project = self._services.active_project()
        if project is None or not project.project_uuid or self._last_bug_scan is None:
            return
        result = self._last_bug_scan
        title = (
            f"Animation Bug Detection: {result.flagged_count} risk indicator(s) in "
            f"{project.name}"
        )
        source_ref = _animation_bug_source_ref(result)
        self._bug_send_btn.setEnabled(False)
        self._bug_send_status.setText("Sending…")

        worker = _SendToTeamBoardWorker(
            self._services, project.project_uuid, title, _format_bug_scan(result),
            source_ref or "animation-bug-detection",
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_bug_findings_sent)
        worker.failed.connect(self._on_bug_findings_send_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_bug_findings_sent(self, task) -> None:
        self._bug_send_btn.setEnabled(True)
        self._bug_send_status.setText(
            "Sent to the Team board." if task is not None
            else "This project isn't linked to a team."
        )

    def _on_bug_findings_send_failed(self, message: str) -> None:
        self._bug_send_btn.setEnabled(True)
        self._bug_send_status.setText(message)

    # --- State Machine Sanity Check ------------------------------------------

    def _build_state_machine_check(self, layout: QVBoxLayout) -> None:
        heading = QLabel("State Machine Health")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Real static analysis (like dead-code detection), not inference: flags states with "
            "no incoming transition anywhere in the file (unreachable), and transitions pointing "
            "to a fileID that doesn't exist in the file (missing target). See the results for the "
            "full caveat, including what 'unreachable' cannot see (e.g. a script calling "
            "Animator.Play by name)."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        row.addStretch(1)
        self._sm_run_btn = QPushButton("Run state machine check")
        self._sm_run_btn.clicked.connect(self._on_sm_check_run)
        row.addWidget(self._sm_run_btn)
        layout.addLayout(row)

        self._sm_result = QTextEdit()
        self._sm_result.setReadOnly(True)
        self._sm_result.setPlaceholderText("Structural findings will appear here.")
        self._sm_result.setFixedHeight(220)
        layout.addWidget(self._sm_result)

        history_title = QLabel("Recent checks")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._sm_history = QTextEdit()
        self._sm_history.setReadOnly(True)
        self._sm_history.setFixedHeight(80)
        layout.addWidget(self._sm_history)

    def _on_sm_check_run(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._sm_run_btn.setEnabled(False)
        self._sm_run_btn.setText("Scanning…")
        self._sm_result.setPlainText("Scanning Animator Controller files…")

        worker = _StateMachineCheckWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_sm_check_done)
        worker.failed.connect(self._on_sm_check_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_sm_check_done(self, result: StateMachineScanResult) -> None:
        self._sm_run_btn.setEnabled(True)
        self._sm_run_btn.setText("Run state machine check")
        self._sm_result.setPlainText(_format_state_machine_scan(result))
        self.usage_changed.emit()
        self._refresh_sm_history()

    def _on_sm_check_failed(self, message: str) -> None:
        self._sm_run_btn.setEnabled(True)
        self._sm_run_btn.setText("Run state machine check")
        self._sm_result.setPlainText(message)

    def _refresh_sm_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._sm_history.setPlainText("Checks are saved once you select an active project.")
            return
        reports = self._services.animation_state_machine_check.history(project.id, limit=5)
        if not reports:
            self._sm_history.setPlainText("No state machine checks saved yet.")
            return
        lines = [
            f"[{r.created_at}] {r.findings.get('controllers_scanned', 0)} controller(s) scanned"
            for r in reports
        ]
        self._sm_history.setPlainText("\n".join(lines))

    # --- Refresh -----------------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project selected. Choose or create one on the Projects screen to run "
                "these scans."
            )
        else:
            self._context_label.setText(f"Active project: {project.name}")
        self._refresh_sm_history()
