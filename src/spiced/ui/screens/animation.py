"""Animation: Animation Bug Detection, State Machine Health, State Machine
& Retarget Validation.

The first two sections are static analysis of ``.controller`` files via
``connectors.unity_controller_scan`` -- no AI provider is used anywhere on
this screen. Animation Bug Detection surfaces *risk indicators*, never
confirmed bugs; State Machine Sanity Check surfaces genuine structural
problems (unreachable states, missing transition targets). Both scans run
on a worker thread for UI responsiveness even though neither calls an AI
provider.

State Machine & Retarget Validation (SPICED_IMPLEMENTATION_BIBLE.md,
Feature 7) reuses State Machine Health's checks above and adds dead-end-
state detection, plus a live-engine retarget check (comparing two
skeletons' bone names via a real Unity Editor call) -- the one thing this
screen does that needs an engine connection.
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
from spiced.automation.animation_bug_detection_live import CAVEAT as LIVE_BUG_DETECTION_CAVEAT
from spiced.automation.finding import Finding
from spiced.automation.mocap_cleanup_assist import CAVEAT as MOCAP_CLEANUP_CAVEAT
from spiced.automation.state_machine_validation import DEFAULT_ALIAS_PREFIXES
from spiced.core.animation_bug_detection import AnimationBugScanResult, detect_animation_bugs
from spiced.core.animation_state_machine_check import NoUnityFolderError, StateMachineScanResult
from spiced.core.unity_test_runner import resolve_unity_editor
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.tool_switcher import build_tool_switcher


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


class _SmvStateCheckWorker(QObject):
    done = Signal(object)  # Finding
    failed = Signal(str)

    def __init__(self, services: Services, project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            finding, _record = self._services.state_machine_validation.check_states(self._project)
            self._services.record_telemetry_event("animation.state_machine_retarget_states_run")
            self.done.emit(finding)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while scanning: {exc}")


class _SmvRetargetWorker(QObject):
    done = Signal(object)  # Finding
    failed = Signal(str)

    def __init__(
        self, services: Services, project, source_model_path: str, target_model_path: str
    ) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._source_model_path = source_model_path
        self._target_model_path = target_model_path

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
            finding, _record = self._services.state_machine_validation.check_retarget(
                self._project, editor.path, self._source_model_path, self._target_model_path
            )
            self._services.record_telemetry_event("animation.state_machine_retarget_bones_run")
            self.done.emit(finding)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during the retarget check: {exc}")


def _format_smv_finding(finding: Finding) -> str:
    lines = [finding.summary, ""]
    if not finding.items:
        lines.append("Nothing was checked.")
        return "\n".join(lines)
    for item in finding.items:
        lines.append(f"- [{item.severity}] {item.message}")
    return "\n".join(lines)


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


def _split_names(text: str) -> list[str]:
    return [n.strip() for n in text.split(",") if n.strip()]


class _LiveBugDetectionWorker(QObject):
    done = Signal(object)  # Finding
    failed = Signal(str)

    def __init__(
        self, services: Services, project, unity_path: str, scene_path: str, marker_name: str,
        foot_bone_names: list[str], tracked_bone_names: list[str], state_names: list[str] | None,
    ) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._unity_path = unity_path
        self._scene_path = scene_path
        self._marker_name = marker_name
        self._foot_bone_names = foot_bone_names
        self._tracked_bone_names = tracked_bone_names
        self._state_names = state_names

    def run(self) -> None:
        try:
            finding, _record = self._services.live_animation_bug_detection.run(
                self._project, self._unity_path, scene_path=self._scene_path,
                marker_name=self._marker_name, foot_bone_names=self._foot_bone_names,
                tracked_bone_names=self._tracked_bone_names, state_names=self._state_names,
            )
            self._services.record_telemetry_event("animation.live_playtest_bug_detection_run")
            self.done.emit(finding)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong during the playtest capture: {exc}")


def _format_live_bug_detection(finding: Finding) -> str:
    lines = [LIVE_BUG_DETECTION_CAVEAT, "", finding.summary, ""]
    if not finding.items:
        lines.append("Nothing to report.")
        return "\n".join(lines)
    for item in finding.items:
        lines.append(f"- [{item.severity}] {item.message}")
    return "\n".join(lines)


class _MocapCleanupWorker(QObject):
    done = Signal(object)  # Finding
    failed = Signal(str)

    def __init__(self, services: Services, project, bvh_path: str,
                 foot_joint_names: list[str] | None) -> None:
        super().__init__()
        self._services = services
        self._project = project
        self._bvh_path = bvh_path
        self._foot_joint_names = foot_joint_names

    def run(self) -> None:
        try:
            finding, _record = self._services.mocap_cleanup_assist.scan(
                self._project, self._bvh_path, foot_joint_names=self._foot_joint_names
            )
            self._services.record_telemetry_event("animation.mocap_cleanup_assist_run")
            self.done.emit(finding)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while scanning the mocap file: {exc}")


def _format_mocap_cleanup(finding: Finding) -> str:
    lines = [MOCAP_CLEANUP_CAVEAT, "", finding.summary, ""]
    if not finding.items:
        lines.append("Nothing to report.")
        return "\n".join(lines)
    for item in finding.items:
        lines.append(f"- [{item.severity}] {item.message}")
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
        content.setObjectName("ScrollContent")
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

        columns, self._stack, self._tool_group = build_tool_switcher(
            self,
            [
                ("Animation Bug Detection", self._build_bug_detection),
                ("State Machine Health", self._build_state_machine_check),
                ("State Machine & Retarget Validation", self._build_smv),
                ("Animation Bug Detection, Live Capture", self._build_live_bug_detection),
                ("Mocap Cleanup Assist", self._build_mocap_cleanup),
            ],
        )
        layout.addLayout(columns, 1)

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
        self._bug_run_btn = PillButton("Scan for risk indicators")
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
        self._bug_send_btn = PillButton("Send to Team Board", ghost=True)
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
        self._sm_run_btn = PillButton("Run state machine check")
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

    # --- State Machine & Retarget Validation (Implementation Bible, Feature 7) ---

    def _build_smv(self, layout: QVBoxLayout) -> None:
        heading = QLabel("State Machine & Retarget Validation")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        state_heading = QLabel("Check the player animation state machine for unreachable states")
        state_heading.setObjectName("SectionTitle")
        layout.addWidget(state_heading)

        state_intro = QLabel(
            "Same unreachable-state and missing-target checks as State Machine Health above, "
            "plus dead-end states -- a state with zero outgoing transitions, which the animator "
            "can never leave via the state machine's own graph."
        )
        state_intro.setObjectName("Muted")
        state_intro.setWordWrap(True)
        layout.addWidget(state_intro)

        state_row = QHBoxLayout()
        state_row.addStretch(1)
        self._smv_state_run_btn = PillButton("Run state machine check")
        self._smv_state_run_btn.clicked.connect(self._on_smv_state_run)
        state_row.addWidget(self._smv_state_run_btn)
        layout.addLayout(state_row)

        self._smv_state_result = QTextEdit()
        self._smv_state_result.setReadOnly(True)
        self._smv_state_result.setPlaceholderText("Unreachable/dead-end findings will appear here.")
        self._smv_state_result.setFixedHeight(160)
        layout.addWidget(self._smv_state_result)

        retarget_heading = QLabel("Validate the retarget mapping before we shoot the mocap session")
        retarget_heading.setObjectName("SectionTitle")
        layout.addWidget(retarget_heading)

        retarget_intro = QLabel(
            "Compares a source and target skeleton's bone names (read live from Unity) and flags "
            "any source bone with no match in the target, either exactly or after stripping a "
            "known naming-convention prefix (default: mixamorig:)."
        )
        retarget_intro.setObjectName("Muted")
        retarget_intro.setWordWrap(True)
        layout.addWidget(retarget_intro)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source model:"))
        self._smv_source_input = QLineEdit()
        self._smv_source_input.setPlaceholderText("Assets/Characters/SourceRig.fbx")
        source_row.addWidget(self._smv_source_input, 1)
        layout.addLayout(source_row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target model:"))
        self._smv_target_input = QLineEdit()
        self._smv_target_input.setPlaceholderText("Assets/Characters/TargetRig.fbx")
        target_row.addWidget(self._smv_target_input, 1)
        layout.addLayout(target_row)

        alias_row = QHBoxLayout()
        alias_row.addWidget(QLabel("Alias prefixes:"))
        self._smv_alias_input = QLineEdit()
        self._smv_alias_input.setPlaceholderText(", ".join(DEFAULT_ALIAS_PREFIXES))
        alias_row.addWidget(self._smv_alias_input, 1)
        self._smv_save_settings_btn = PillButton("Save as project default", ghost=True)
        self._smv_save_settings_btn.clicked.connect(self._on_smv_save_settings)
        alias_row.addWidget(self._smv_save_settings_btn)
        layout.addLayout(alias_row)

        retarget_run_row = QHBoxLayout()
        retarget_run_row.addStretch(1)
        self._smv_retarget_run_btn = PillButton("Check retarget mapping")
        self._smv_retarget_run_btn.clicked.connect(self._on_smv_retarget_run)
        retarget_run_row.addWidget(self._smv_retarget_run_btn)
        layout.addLayout(retarget_run_row)

        self._smv_retarget_result = QTextEdit()
        self._smv_retarget_result.setReadOnly(True)
        self._smv_retarget_result.setPlaceholderText("Unmapped-bone findings will appear here.")
        self._smv_retarget_result.setFixedHeight(160)
        layout.addWidget(self._smv_retarget_result)

        history_title = QLabel("Recent runs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._smv_history = QTextEdit()
        self._smv_history.setReadOnly(True)
        self._smv_history.setFixedHeight(80)
        layout.addWidget(self._smv_history)

    def _on_smv_state_run(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._smv_state_run_btn.setEnabled(False)
        self._smv_state_run_btn.setText("Scanning…")
        self._smv_state_result.setPlainText("Scanning Animator Controller files…")

        worker = _SmvStateCheckWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_smv_state_done)
        worker.failed.connect(self._on_smv_state_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_smv_state_done(self, finding: Finding) -> None:
        self._smv_state_run_btn.setEnabled(True)
        self._smv_state_run_btn.setText("Run state machine check")
        self._smv_state_result.setPlainText(_format_smv_finding(finding))
        self.usage_changed.emit()
        self._refresh_smv_history()

    def _on_smv_state_failed(self, message: str) -> None:
        self._smv_state_run_btn.setEnabled(True)
        self._smv_state_run_btn.setText("Run state machine check")
        self._smv_state_result.setPlainText(message)

    def _on_smv_save_settings(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        self._services.projects.set_retarget_alias_prefixes(
            project.id, self._smv_alias_input.text().strip() or None
        )
        self.refresh()

    def _on_smv_retarget_run(self) -> None:
        project = self._services.active_project()
        if project is None or not project.path:
            QMessageBox.information(
                self,
                "Pick a project first",
                "Select a project with a connected Unity folder on the Projects screen.",
            )
            return
        source = self._smv_source_input.text().strip()
        target = self._smv_target_input.text().strip()
        if not source or not target:
            QMessageBox.information(
                self, "Missing input", "Enter both a source and target model asset path first."
            )
            return
        self._smv_retarget_run_btn.setEnabled(False)
        self._smv_retarget_run_btn.setText("Checking…")
        self._smv_retarget_result.setPlainText(
            "Launching Unity and comparing skeletons (this can take a while)…"
        )

        worker = _SmvRetargetWorker(self._services, project, source, target)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_smv_retarget_done)
        worker.failed.connect(self._on_smv_retarget_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_smv_retarget_done(self, finding: Finding) -> None:
        self._smv_retarget_run_btn.setEnabled(True)
        self._smv_retarget_run_btn.setText("Check retarget mapping")
        self._smv_retarget_result.setPlainText(_format_smv_finding(finding))
        self.usage_changed.emit()
        self._refresh_smv_history()

    def _on_smv_retarget_failed(self, message: str) -> None:
        self._smv_retarget_run_btn.setEnabled(True)
        self._smv_retarget_run_btn.setText("Check retarget mapping")
        self._smv_retarget_result.setPlainText(message)

    def _refresh_smv_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._smv_history.setPlainText("Runs are saved once you select an active project.")
            return
        records = self._services.state_machine_validation.history(project.id, limit=5)
        if not records:
            self._smv_history.setPlainText("No runs saved yet.")
            return
        self._smv_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
        )

    # --- Automated Animation Bug Detection, Live Capture (Implementation Bible, Feature 11) ---

    def _build_live_bug_detection(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Animation Bug Detection, Live Capture")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Drives a real Unity Play Mode capture through the requested states and checks the "
            "actual evaluated pose/bone data for foot sliding, T-posing, and snap transitions -- "
            "Spiced's one deliberate exception to its local-first/read-only default, kept "
            "alongside the static Animation Bug Detection risk-indicator scan above rather than "
            "replacing it."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scene_row = QHBoxLayout()
        scene_row.addWidget(QLabel("Scene:"))
        self._live_scene_input = QLineEdit()
        self._live_scene_input.setPlaceholderText("Assets/Scenes/Main.unity")
        scene_row.addWidget(self._live_scene_input, 1)
        layout.addLayout(scene_row)

        marker_row = QHBoxLayout()
        marker_row.addWidget(QLabel("Character root:"))
        self._live_marker_input = QLineEdit()
        self._live_marker_input.setPlaceholderText("Player")
        marker_row.addWidget(self._live_marker_input, 1)
        layout.addLayout(marker_row)

        foot_row = QHBoxLayout()
        foot_row.addWidget(QLabel("Foot bones:"))
        self._live_foot_bones_input = QLineEdit()
        self._live_foot_bones_input.setPlaceholderText("LeftFoot, RightFoot")
        foot_row.addWidget(self._live_foot_bones_input, 1)
        layout.addLayout(foot_row)

        tracked_row = QHBoxLayout()
        tracked_row.addWidget(QLabel("Tracked bones:"))
        self._live_tracked_bones_input = QLineEdit()
        self._live_tracked_bones_input.setPlaceholderText("Spine, LeftUpperArm, RightUpperArm, ...")
        tracked_row.addWidget(self._live_tracked_bones_input, 1)
        layout.addLayout(tracked_row)

        states_row = QHBoxLayout()
        states_row.addWidget(QLabel("States:"))
        self._live_states_input = QLineEdit()
        self._live_states_input.setPlaceholderText(
            "Idle, Walk, Jump (blank = inferred from .controller files)"
        )
        states_row.addWidget(self._live_states_input, 1)
        layout.addLayout(states_row)

        run_row = QHBoxLayout()
        run_row.addStretch(1)
        self._live_run_btn = PillButton("Run live playtest capture")
        self._live_run_btn.clicked.connect(self._on_live_run)
        run_row.addWidget(self._live_run_btn)
        layout.addLayout(run_row)

        self._live_result = QTextEdit()
        self._live_result.setReadOnly(True)
        self._live_result.setPlaceholderText(
            "Foot-sliding/T-pose/snap-transition findings will appear here."
        )
        self._live_result.setFixedHeight(200)
        layout.addWidget(self._live_result)

        history_title = QLabel("Recent runs")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._live_history = QTextEdit()
        self._live_history.setReadOnly(True)
        self._live_history.setFixedHeight(80)
        layout.addWidget(self._live_history)

    def _on_live_run(self) -> None:
        project = self._services.active_project()
        if project is None or not project.path:
            QMessageBox.information(
                self, "Pick a project first",
                "Select a project with a connected Unity folder on the Projects screen.",
            )
            return
        scene_path = self._live_scene_input.text().strip()
        marker_name = self._live_marker_input.text().strip()
        foot_bones = _split_names(self._live_foot_bones_input.text())
        tracked_bones = _split_names(self._live_tracked_bones_input.text())
        if not scene_path or not marker_name or not foot_bones or not tracked_bones:
            QMessageBox.information(
                self, "Missing input",
                "Enter a scene path, character root name, and at least one foot bone and "
                "tracked bone first.",
            )
            return
        states = _split_names(self._live_states_input.text()) or None

        required_version = project.engine_metadata.get("unity_version")
        editor = resolve_unity_editor(required_version, project.unity_editor_path_override)
        if editor is None:
            QMessageBox.information(
                self, "Unity not found",
                f"Unity {required_version or '(unknown version)'} isn't available. Install it "
                "via Unity Hub, or set a manual Editor path on the Projects screen.",
            )
            return

        self._live_run_btn.setEnabled(False)
        self._live_run_btn.setText("Capturing…")
        self._live_result.setPlainText(
            "Launching Unity and playing through the requested states (this can take a while)…"
        )

        worker = _LiveBugDetectionWorker(
            self._services, project, editor.path, scene_path, marker_name, foot_bones,
            tracked_bones, states,
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_live_run_done)
        worker.failed.connect(self._on_live_run_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_live_run_done(self, finding: Finding) -> None:
        self._live_run_btn.setEnabled(True)
        self._live_run_btn.setText("Run live playtest capture")
        self._live_result.setPlainText(_format_live_bug_detection(finding))
        self.usage_changed.emit()
        self._refresh_live_history()

    def _on_live_run_failed(self, message: str) -> None:
        self._live_run_btn.setEnabled(True)
        self._live_run_btn.setText("Run live playtest capture")
        self._live_result.setPlainText(message)

    def _refresh_live_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._live_history.setPlainText("Runs are saved once you select an active project.")
            return
        records = self._services.live_animation_bug_detection.history(project.id, limit=5)
        if not records:
            self._live_history.setPlainText("No runs saved yet.")
            return
        self._live_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
        )

    # --- Mocap Cleanup Assist (Implementation Bible, Feature 12) -------------

    def _build_mocap_cleanup(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Mocap Cleanup Assist")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "Detection only, no auto-fix. Scans a raw BVH mocap take -- before it's even "
            "imported, no live engine connection needed -- for foot sliding (the same helper "
            "the live capture above uses) and single-frame jitter (a joint's rotation spiking "
            "away from and immediately back to its neighbors' trend)."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        file_row = QHBoxLayout()
        self._mocap_file_input = QLineEdit()
        self._mocap_file_input.setPlaceholderText("Path to a .bvh mocap file")
        file_row.addWidget(self._mocap_file_input, 1)
        self._mocap_browse_btn = PillButton("Browse…")
        self._mocap_browse_btn.clicked.connect(self._on_mocap_browse)
        file_row.addWidget(self._mocap_browse_btn)
        layout.addLayout(file_row)

        foot_row = QHBoxLayout()
        foot_row.addWidget(QLabel("Foot joints:"))
        self._mocap_foot_joints_input = QLineEdit()
        self._mocap_foot_joints_input.setPlaceholderText(
            "LeftFoot, RightFoot (blank = auto-guessed by name)"
        )
        foot_row.addWidget(self._mocap_foot_joints_input, 1)
        self._mocap_run_btn = PillButton("Scan mocap take")
        self._mocap_run_btn.clicked.connect(self._on_mocap_run)
        foot_row.addWidget(self._mocap_run_btn)
        layout.addLayout(foot_row)

        self._mocap_result = QTextEdit()
        self._mocap_result.setReadOnly(True)
        self._mocap_result.setPlaceholderText("Foot-sliding/jitter findings will appear here.")
        self._mocap_result.setFixedHeight(200)
        layout.addWidget(self._mocap_result)

        history_title = QLabel("Recent scans")
        history_title.setObjectName("SectionTitle")
        layout.addWidget(history_title)
        self._mocap_history = QTextEdit()
        self._mocap_history.setReadOnly(True)
        self._mocap_history.setFixedHeight(80)
        layout.addWidget(self._mocap_history)

    def _on_mocap_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Pick a BVH mocap file", "", "BVH (*.bvh)")
        if path:
            self._mocap_file_input.setText(path)

    def _on_mocap_run(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project on the Projects screen."
            )
            return
        bvh_path = self._mocap_file_input.text().strip()
        if not bvh_path or not Path(bvh_path).is_file():
            QMessageBox.information(
                self, "Pick a file", "Enter or browse to a .bvh mocap file first."
            )
            return
        foot_joint_names = _split_names(self._mocap_foot_joints_input.text()) or None

        self._mocap_run_btn.setEnabled(False)
        self._mocap_run_btn.setText("Scanning…")
        self._mocap_result.setPlainText("Scanning mocap take…")

        worker = _MocapCleanupWorker(self._services, project, bvh_path, foot_joint_names)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_mocap_done)
        worker.failed.connect(self._on_mocap_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_mocap_done(self, finding: Finding) -> None:
        self._mocap_run_btn.setEnabled(True)
        self._mocap_run_btn.setText("Scan mocap take")
        self._mocap_result.setPlainText(_format_mocap_cleanup(finding))
        self.usage_changed.emit()
        self._refresh_mocap_history()

    def _on_mocap_failed(self, message: str) -> None:
        self._mocap_run_btn.setEnabled(True)
        self._mocap_run_btn.setText("Scan mocap take")
        self._mocap_result.setPlainText(message)

    def _refresh_mocap_history(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._mocap_history.setPlainText("Runs are saved once you select an active project.")
            return
        records = self._services.mocap_cleanup_assist.history(project.id, limit=5)
        if not records:
            self._mocap_history.setPlainText("No scans saved yet.")
            return
        self._mocap_history.setPlainText(
            "\n".join(f"[{r.created_at}] {r.summary}" for r in records)
        )

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
        self._refresh_smv_history()
        self._refresh_live_history()
        self._refresh_mocap_history()
        if project is not None:
            self._smv_alias_input.setText(project.retarget_alias_prefixes or "")
