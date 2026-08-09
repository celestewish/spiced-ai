"""Right-hand project context panel."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.crunch_awareness import detect_crunch_pattern
from spiced.core.session_summary import ProviderNotReadyError, SessionSummaryResult
from spiced.core.widget_preferences import (
    CONTEXT_PANEL_WIDGETS,
    load_preferences,
    merge_and_dump,
)
from spiced.storage.projects import Project
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widget_customize_dialog import WidgetCustomizeDialog
from spiced.ui.widgets.pill_button import PillButton

# Role-Based Dashboards (Phase J, Cross-Role & Team Glue #4): the
# disciplines this panel knows how to summarize, each backed by a genuinely
# existing feature's most recently SAVED report -- never a live re-scan,
# since ContextPanel.refresh() runs synchronously on the UI thread and must
# stay fast. Covers 4 of the suggested discipline values (see
# ui.screens.team.SUGGESTED_DISCIPLINES); "design" has no existing feature
# with a comparable saved-report summary yet, so it's deliberately not
# covered here.
_ROLE_SUMMARY_LABELS = {
    "artist": "Asset Review Queue",
    "audio": "Audio Implementation Checklist",
    "animation": "State Machine Health",
    "programmer": "Code Health",
}


def _role_summary_text(services: Services, project: Project, discipline: str) -> str | None:
    """The one-line summary shown for ``discipline``, or None if this
    discipline isn't one of the four covered (see ``_ROLE_SUMMARY_LABELS``)."""
    if discipline == "artist":
        reports = services.asset_review_queue.history(project.id, limit=1)
        if not reports:
            return f"{_ROLE_SUMMARY_LABELS[discipline]}: no saved runs yet -- see the Art screen."
        flagged = sum(1 for f in reports[0].findings if not f.get("passed", True))
        return f"{_ROLE_SUMMARY_LABELS[discipline]}: {flagged} asset(s) flagged in the last run."
    if discipline == "audio":
        reports = services.audio_implementation_checklist.history(project.id, limit=1)
        if not reports:
            return f"{_ROLE_SUMMARY_LABELS[discipline]}: no saved runs yet -- see the Audio screen."
        f = reports[0].findings
        gaps = len(f.get("unmatched_references", [])) + len(f.get("unreferenced_audio_files", []))
        return f"{_ROLE_SUMMARY_LABELS[discipline]}: {gaps} gap(s) in the last run."
    if discipline == "animation":
        reports = services.animation_state_machine_check.history(project.id, limit=1)
        if not reports:
            return (
                f"{_ROLE_SUMMARY_LABELS[discipline]}: no saved checks yet -- see the "
                "Animation screen."
            )
        f = reports[0].findings
        flagged = len(f.get("unreachable_states", [])) + len(f.get("missing_targets", []))
        return f"{_ROLE_SUMMARY_LABELS[discipline]}: {flagged} issue(s) in the last check."
    if discipline == "programmer":
        reports = services.code_health.history(project.id, limit=1)
        if not reports:
            return (
                f"{_ROLE_SUMMARY_LABELS[discipline]}: no saved reviews yet -- see the "
                "Debugging Buddy screen."
            )
        metrics = reports[0].metrics
        longest = len(metrics.get("longest_functions", []))
        todos = metrics.get("todo_count", 0)
        return f"{_ROLE_SUMMARY_LABELS[discipline]}: {longest} long function(s), {todos} TODO(s)."
    return None


class _RoleDashboardWorker(QObject):
    """Fetches the signed-in user's discipline (a network call, via
    TeamService) then a local report summary for it -- run off the UI thread
    since ContextPanel.refresh() itself must stay fast and synchronous."""

    done = Signal(object)  # str | None (the summary text, or None to show nothing)
    failed = Signal()

    def __init__(self, services: Services, project: Project) -> None:
        super().__init__()
        self._services = services
        self._project = project

    def run(self) -> None:
        try:
            discipline = self._services.teams.my_discipline(self._project.project_uuid)
            if not discipline:
                self.done.emit(None)
                return
            self.done.emit(_role_summary_text(self._services, self._project, discipline))
        except Exception:
            self.failed.emit()


class _SessionSummaryWorker(QObject):
    done = Signal(object, bool)  # SessionSummaryResult, synced_to_team
    failed = Signal(str)

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services

    def run(self) -> None:
        try:
            project = self._services.active_project()
            if project is None:
                self.failed.emit("Select an active project first.")
                return
            provider = self._services.build_provider()
            team_mode = self._services.team_mode_enabled()
            team_members = self._services.team_prompt_context(project) if team_mode else None
            result = self._services.session_summaries.summarize(
                provider,
                project,
                self._services.app_started_at,
                team_mode=team_mode,
                team_members=team_members,
                record_usage=self._services.usage.record_prompt,
            )
            synced = False
            if team_mode:
                synced = self._services.sync_session_summary(project, result.summary)
            self.done.emit(result, synced)
        except ProviderNotReadyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Something went wrong while summarizing the session: {exc}")


class ContextPanel(QFrame):
    """Shows lightweight, always-visible context: project count and usage."""

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.setObjectName("ContextPanel")
        self._services = services
        # Crunch-Pattern Awareness (Phase F): dismissed for the current app
        # session only — see _build_crunch_awareness_section below for why
        # persisting the dismissal across restarts is left as a documented
        # nice-to-have rather than built now.
        self._crunch_dismissed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        heading = QLabel("Project context")
        heading.setObjectName("SectionTitle")
        header_row.addWidget(heading)
        header_row.addStretch(1)
        # Customizable Dashboard Widgets (Phase L, Phase 2 tier -- scoped
        # down to show/hide + reorder, see core.widget_preferences): opens a
        # small list dialog for the sections below, rather than the full
        # spec's drag-and-drop resize.
        self._customize_btn = PillButton("Customize", ghost=True)
        self._customize_btn.clicked.connect(self._on_customize)
        header_row.addWidget(self._customize_btn)
        layout.addLayout(header_row)

        # Every section below is built into its own container widget and
        # tracked in ``self._section_widgets`` so ``_apply_widget_layout``
        # can show/hide and reorder them independently, per the developer's
        # saved widget preferences (see core.widget_preferences).
        self._sections_layout = QVBoxLayout()
        self._sections_layout.setSpacing(10)
        layout.addLayout(self._sections_layout)
        self._section_widgets: dict[str, QWidget] = {}

        self._build_project_info_section()
        self._build_usage_section()
        self._build_session_section()
        self._build_crunch_awareness_section()
        self._build_role_dashboard_section()

        self._apply_widget_layout()

        self._build_build_alert_section(layout)

        layout.addStretch(1)

        footer = QLabel("Spiced keeps everything local. You decide what to share.")
        footer.setObjectName("Muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self.refresh()

    def _register_section(self, widget_id: str, container: QWidget) -> None:
        self._section_widgets[widget_id] = container
        self._sections_layout.addWidget(container)

    @staticmethod
    def _section_container() -> tuple[QWidget, QVBoxLayout]:
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(6)
        return container, container_layout

    # --- Customizable Dashboard Widgets (Phase L) ---------------------------

    def _on_customize(self) -> None:
        preferences = load_preferences(
            self._services.widget_preferences_json(), CONTEXT_PANEL_WIDGETS
        )
        dialog = WidgetCustomizeDialog(
            CONTEXT_PANEL_WIDGETS, preferences, parent=self, title="Customize project context"
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.result_preferences()
            new_json = merge_and_dump(self._services.widget_preferences_json(), updated)
            self._services.set_widget_preferences_json(new_json)
            self._apply_widget_layout()

    def _apply_widget_layout(self) -> None:
        """Show/hide and reorder each registered section per the developer's
        saved preferences. Re-adding a widget to a QVBoxLayout it's already
        in moves it to the end, so iterating specs in their saved order
        produces exactly that final layout order."""
        preferences = load_preferences(
            self._services.widget_preferences_json(), CONTEXT_PANEL_WIDGETS
        )
        ordered_specs = sorted(CONTEXT_PANEL_WIDGETS, key=lambda s: preferences[s.id].order)
        for spec in ordered_specs:
            widget = self._section_widgets.get(spec.id)
            if widget is None:
                continue
            self._sections_layout.removeWidget(widget)
            self._sections_layout.addWidget(widget)
            widget.setVisible(preferences[spec.id].visible)

    # --- Project info / Usage (Phase L: made customizable) ------------------

    def _build_project_info_section(self) -> None:
        container, layout = self._section_container()
        self._active_label = QLabel()
        self._active_label.setWordWrap(True)
        layout.addWidget(self._active_label)

        self._unity_label = QLabel()
        self._unity_label.setObjectName("Muted")
        self._unity_label.setWordWrap(True)
        layout.addWidget(self._unity_label)

        self._projects_label = QLabel()
        self._projects_label.setObjectName("Muted")
        self._projects_label.setWordWrap(True)
        layout.addWidget(self._projects_label)
        self._register_section("project_info", container)

    def _build_usage_section(self) -> None:
        container, layout = self._section_container()
        usage_title = QLabel("Usage")
        usage_title.setObjectName("SectionTitle")
        layout.addWidget(usage_title)

        self._usage_pill = QLabel()
        self._usage_pill.setObjectName("UsagePill")
        self._usage_pill.setWordWrap(True)
        layout.addWidget(self._usage_pill)
        self._register_section("usage", container)

    # --- Session Summaries (Phase B) ----------------------------------------

    def _build_session_section(self) -> None:
        container, layout = self._section_container()
        title = QLabel("Session")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        intro = QLabel(
            "Recap what was tested, fixed, and still open since your last summary. Local "
            "always; also shared with your team when Team Mode is on and this project is "
            "linked."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._end_session_btn = PillButton("Summarize / end session", ghost=True)
        self._end_session_btn.clicked.connect(self._on_end_session)
        layout.addWidget(self._end_session_btn)

        self._session_status = QLabel("")
        self._session_status.setObjectName("Muted")
        self._session_status.setWordWrap(True)
        layout.addWidget(self._session_status)

        recent_title = QLabel("Recent sessions")
        recent_title.setObjectName("Muted")
        layout.addWidget(recent_title)
        self._recent_sessions = QLabel("No sessions summarized yet.")
        self._recent_sessions.setObjectName("Muted")
        self._recent_sessions.setWordWrap(True)
        layout.addWidget(self._recent_sessions)
        self._register_section("session", container)

    def _on_end_session(self) -> None:
        if self._services.active_project() is None:
            QMessageBox.information(
                self, "Pick a project first", "Select an active project on the Projects screen."
            )
            return
        self._end_session_btn.setEnabled(False)
        self._end_session_btn.setText("Summarizing…")
        self._session_status.setText("Gathering what changed and thinking it through…")

        worker = _SessionSummaryWorker(self._services)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_session_done)
        worker.failed.connect(self._on_session_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_session_done(self, result: SessionSummaryResult, synced: bool) -> None:
        self._end_session_btn.setEnabled(True)
        self._end_session_btn.setText("Summarize / end session")
        note = " Shared with your team." if synced else ""
        self._session_status.setText(result.response_text + note)
        self._refresh_recent_sessions()

    def _on_session_failed(self, message: str) -> None:
        self._end_session_btn.setEnabled(True)
        self._end_session_btn.setText("Summarize / end session")
        self._session_status.setText(message)

    def _refresh_recent_sessions(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._recent_sessions.setText("Sessions are saved once you select an active project.")
            return
        sessions = self._services.session_summaries.history(project.id, limit=5)
        if not sessions:
            self._recent_sessions.setText("No sessions summarized yet.")
            return
        lines = []
        for s in sessions:
            synced_note = " (shared)" if s.synced_to_team else ""
            blurb = (s.ai_summary or "").strip().splitlines()
            first_line = next((line for line in blurb if line.strip()), "")
            lines.append(f"[{s.created_at}]{synced_note} {first_line}")
        self._recent_sessions.setText("\n".join(lines))

    # --- Crunch-Pattern Awareness (Phase F, Dev Wellbeing) -------------------
    #
    # Purely local: reuses the same session_summaries history the Session
    # section above already reads, via core.crunch_awareness.
    # detect_crunch_pattern -- no new capture mechanism, no AI call, and
    # (hard privacy rule, see that module's docstring) no path to
    # TeamService/BackendClient, even for team-linked projects. A quiet,
    # dismissible note: dismissing hides it for the rest of this app run.
    # Persisting the dismissal across restarts would need a new local
    # settings key; left as a documented nice-to-have rather than built now,
    # since re-showing an informational note on next launch is a minor
    # inconvenience, not a privacy or correctness issue.

    def _build_crunch_awareness_section(self) -> None:
        container, layout = self._section_container()
        self._crunch_note = QLabel("")
        self._crunch_note.setObjectName("Muted")
        self._crunch_note.setWordWrap(True)
        self._crunch_note.setVisible(False)
        layout.addWidget(self._crunch_note)

        self._crunch_dismiss_btn = PillButton("Dismiss", ghost=True)
        self._crunch_dismiss_btn.setVisible(False)
        self._crunch_dismiss_btn.clicked.connect(self._on_dismiss_crunch_note)
        layout.addWidget(self._crunch_dismiss_btn)
        self._register_section("crunch_note", container)

    def _on_dismiss_crunch_note(self) -> None:
        self._crunch_dismissed = True
        self._crunch_note.setVisible(False)
        self._crunch_dismiss_btn.setVisible(False)

    def _refresh_crunch_awareness(self) -> None:
        if self._crunch_dismissed:
            return
        project = self._services.active_project()
        if project is None:
            self._crunch_note.setVisible(False)
            self._crunch_dismiss_btn.setVisible(False)
            return
        summaries = self._services.session_summaries.history(project.id, limit=100)
        result = detect_crunch_pattern(summaries)
        message = result.message
        if message is None:
            self._crunch_note.setVisible(False)
            self._crunch_dismiss_btn.setVisible(False)
            return
        self._crunch_note.setText(message)
        self._crunch_note.setVisible(True)
        self._crunch_dismiss_btn.setVisible(True)

    # --- Role-Based Dashboards (Phase J, Cross-Role & Team Glue #4) ---------
    #
    # Only shown for a team-linked project whose signed-in user has a
    # discipline set (see core.team_service.TeamService.my_discipline) that
    # is one of the four this panel knows how to summarize (see
    # _ROLE_SUMMARY_LABELS above). Hidden entirely otherwise -- solo/local-
    # only projects, unlinked team projects, no discipline set, or a
    # discipline this panel doesn't cover yet (e.g. "design").

    def _build_role_dashboard_section(self) -> None:
        container, layout = self._section_container()
        self._role_title = QLabel("Your discipline")
        self._role_title.setObjectName("SectionTitle")
        self._role_title.setVisible(False)
        layout.addWidget(self._role_title)

        self._role_summary = QLabel("")
        self._role_summary.setObjectName("Muted")
        self._role_summary.setWordWrap(True)
        self._role_summary.setVisible(False)
        layout.addWidget(self._role_summary)
        self._register_section("role_dashboard", container)

    def _refresh_role_dashboard(self) -> None:
        project = self._services.active_project()
        if project is None or not project.project_uuid or not self._services.auth.is_logged_in():
            self._role_title.setVisible(False)
            self._role_summary.setVisible(False)
            return

        worker = _RoleDashboardWorker(self._services, project)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_role_dashboard_done)
        worker.failed.connect(self._on_role_dashboard_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_role_dashboard_done(self, summary: str | None) -> None:
        if not summary:
            self._role_title.setVisible(False)
            self._role_summary.setVisible(False)
            return
        self._role_title.setVisible(True)
        self._role_summary.setText(summary)
        self._role_summary.setVisible(True)

    def _on_role_dashboard_failed(self) -> None:
        self._role_title.setVisible(False)
        self._role_summary.setVisible(False)

    # --- Build alerts (Automated Build Pipeline, Phase D) -------------------
    #
    # Per spec, only a build *failure* interrupts the developer — a
    # successful scheduled/commit build stays quiet. This label starts
    # hidden and only appears when ``show_build_failure`` is called (see
    # ``ui/build_scheduler.py``, which wires this up for the nightly
    # scheduler; the Testing screen's manual "Run build now" button shows
    # its own failure inline instead, since the developer is looking right
    # at it when it happens).

    def _build_build_alert_section(self, layout: QVBoxLayout) -> None:
        self._build_alert = QLabel("")
        self._build_alert.setObjectName("Muted")
        self._build_alert.setWordWrap(True)
        self._build_alert.setVisible(False)
        layout.addWidget(self._build_alert)

    def show_build_failure(self, project_name: str, message: str) -> None:
        trimmed = (message or "").strip().splitlines()
        first_line = next((line for line in trimmed if line.strip()), "").strip()
        detail = first_line or "see Testing for details."
        self._build_alert.setText(f"⚠ Scheduled build failed for {project_name}: {detail}")
        self._build_alert.setVisible(True)

    def clear_build_alert(self) -> None:
        self._build_alert.setVisible(False)
        self._build_alert.setText("")

    # --- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
        active = self._services.active_project()
        if active is None:
            self._active_label.setText("No active project selected.")
            self._unity_label.setText("Choose one on the Projects screen to add Unity context.")
        else:
            self._active_label.setText(f"Active: {active.name}")
            if active.is_valid_unity:
                version = active.engine_metadata.get("unity_version")
                suffix = f" (Unity {version})" if version else ""
                self._unity_label.setText(f"Unity folder connected{suffix}.")
            elif active.path:
                self._unity_label.setText("Folder set, but not recognized as a Unity project.")
            else:
                self._unity_label.setText("No Unity folder connected yet.")

        count = len(self._services.projects.list_projects())
        word = "project" if count == 1 else "projects"
        self._projects_label.setText(f"{count} {word} saved locally.")
        self._usage_pill.setText(self._services.usage.status().summary())
        self._refresh_recent_sessions()
        self._refresh_crunch_awareness()
        self._refresh_role_dashboard()
