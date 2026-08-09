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

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
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
        if project is not None:
            self._smv_alias_input.setText(project.retarget_alias_prefixes or "")
