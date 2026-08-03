"""Right-hand project context panel."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QFrame, QLabel, QMessageBox, QPushButton, QVBoxLayout

from spiced.app.services import Services
from spiced.core.session_summary import ProviderNotReadyError, SessionSummaryResult


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
        self._thread: QThread | None = None
        self._worker: QObject | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        heading = QLabel("Project context")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

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

        layout.addSpacing(10)
        usage_title = QLabel("Usage")
        usage_title.setObjectName("SectionTitle")
        layout.addWidget(usage_title)

        self._usage_pill = QLabel()
        self._usage_pill.setObjectName("UsagePill")
        self._usage_pill.setWordWrap(True)
        layout.addWidget(self._usage_pill)

        self._build_session_section(layout)

        layout.addStretch(1)

        footer = QLabel("Spiced keeps everything local. You decide what to share.")
        footer.setObjectName("Muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self.refresh()

    # --- Session Summaries (Phase B) ----------------------------------------

    def _build_session_section(self, layout: QVBoxLayout) -> None:
        layout.addSpacing(10)
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

        self._end_session_btn = QPushButton("Summarize / end session")
        self._end_session_btn.setObjectName("Ghost")
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

    def _on_end_session(self) -> None:
        if self._services.active_project() is None:
            QMessageBox.information(
                self, "Pick a project first", "Select an active project on the Projects screen."
            )
            return
        self._end_session_btn.setEnabled(False)
        self._end_session_btn.setText("Summarizing…")
        self._session_status.setText("Gathering what changed and thinking it through…")

        self._thread = QThread()
        self._worker = _SessionSummaryWorker(self._services)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_session_done)
        self._worker.failed.connect(self._on_session_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

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
