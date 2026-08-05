"""In-app QTimer-based nightly build scheduler (Automated Build Pipeline).

Per the approved plan, "on a schedule" is an in-app scheduler only: a QTimer
that fires while Spiced is running. It deliberately does **not** register
anything with the OS's own task scheduler — that would be a system-settings
change outside this feature's scope. If Spiced isn't running at a project's
scheduled time, that day's build simply doesn't happen; the Projects-screen
copy for this toggle says so explicitly.

Runs due builds on a worker thread, same pattern as every other long-running
action in this app (see ``ui/screens/testing.py``'s ``_UnityRunWorker``).
Per spec, a successful scheduled build stays quiet — only a failure is
surfaced, via ``build_failed`` (the Context Panel listens for this) and, for
a team-linked project, a real Notification Center entry (see
``_notify_build_failure`` below, Phase K, section 9 part 1's "migrate the
existing build-failure signal into a real event source" instruction). The
Context Panel note stays -- it's the only surfacing a solo/local-only build
ever gets, since Notifications require a team.
"""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QObject, QTimer, Signal

from spiced.app.services import Services
from spiced.core.build_pipeline import BuildNotEnabledError, BuildUnavailableError
from spiced.storage.build_reports import TRIGGER_SCHEDULED
from spiced.ui.thread_utils import launch_worker

# Once a minute is plenty of resolution for a "HH:MM" schedule.
_CHECK_INTERVAL_MS = 60_000


class _ScheduledBuildWorker(QObject):
    build_done = Signal(int, str, bool, str)  # project_id, project_name, succeeded, message
    finished = Signal()

    def __init__(self, services: Services, project_ids: list[int]) -> None:
        super().__init__()
        self._services = services
        self._project_ids = project_ids

    def run(self) -> None:
        for project_id in self._project_ids:
            try:
                project = self._services.projects.get_project(project_id)
            except KeyError:
                continue
            try:
                report = self._services.run_build(
                    project,
                    trigger=TRIGGER_SCHEDULED,
                    editor_override=project.unity_editor_path_override,
                )
            except (BuildNotEnabledError, BuildUnavailableError) as exc:
                self.build_done.emit(project.id, project.name, False, str(exc))
                continue
            except Exception as exc:  # surfaced calmly; never crashes the app
                self.build_done.emit(
                    project.id, project.name, False, f"Something went wrong: {exc}"
                )
                continue
            if report.succeeded:
                self.build_done.emit(project.id, project.name, True, "")
            else:
                message = report.log_tail or "The scheduled build did not succeed."
                self.build_done.emit(project.id, project.name, False, message)
        self.finished.emit()


class _BuildFailureNotifyWorker(QObject):
    """Notification Center event source (Phase K, #a): for a team-linked
    project, create a real ``Notification`` for whoever's relevant to
    "build_failed" (see ``core.notification_routing``). Best-effort and
    silent either way -- ``TeamService.notify_relevant_members_for_project_event``
    already swallows backend/auth errors, and a solo/unlinked project simply
    has nothing to notify (project.project_uuid is falsy)."""

    finished = Signal()

    def __init__(
        self, services: Services, project_id: int, project_name: str, message: str
    ) -> None:
        super().__init__()
        self._services = services
        self._project_id = project_id
        self._project_name = project_name
        self._message = message

    def run(self) -> None:
        try:
            project = self._services.projects.get_project(self._project_id)
        except KeyError:
            self.finished.emit()
            return
        if project.project_uuid:
            lines = (self._message or "").strip().splitlines()
            detail = next((line for line in lines if line.strip()), "").strip()
            self._services.teams.notify_relevant_members_for_project_event(
                project.project_uuid,
                "build_failed",
                f"Scheduled build failed: {self._project_name}",
                detail or "See Testing for details.",
                subject_type="build",
                subject_id=str(self._project_id),
            )
        self.finished.emit()


class BuildScheduler(QObject):
    """Owns the QTimer that checks every project's nightly build schedule."""

    build_failed = Signal(str, str)  # project_name, message
    build_report_saved = Signal()

    def __init__(self, services: Services, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._last_fired: dict[int, date] = {}
        # Guards _check_due_projects re-entrancy (only one batch at a time) --
        # separate from thread/worker lifetime bookkeeping, which
        # launch_worker owns via self._active_threads/_active_workers so a
        # still-running QThread never loses its only Python reference.
        self._batch_running = False
        self._timer = QTimer(self)
        self._timer.setInterval(_CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._check_due_projects)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _check_due_projects(self) -> None:
        if self._batch_running:
            return  # a scheduled batch is already running; check again next tick
        now = datetime.now()
        current_hhmm = now.strftime("%H:%M")
        today = now.date()
        due_ids: list[int] = []
        for project in self._services.projects.list_projects():
            if not (project.build_pipeline_enabled and project.build_schedule_enabled):
                continue
            if not project.build_schedule_time or project.build_schedule_time != current_hhmm:
                continue
            if self._last_fired.get(project.id) == today:
                continue
            self._last_fired[project.id] = today
            due_ids.append(project.id)
        if not due_ids:
            return
        self._start_batch(due_ids)

    def _start_batch(self, project_ids: list[int]) -> None:
        self._batch_running = True
        worker = _ScheduledBuildWorker(self._services, project_ids)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.build_done.connect(self._on_build_done)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        thread.start()

    def _on_build_done(
        self, project_id: int, project_name: str, succeeded: bool, message: str
    ) -> None:
        self.build_report_saved.emit()
        if not succeeded:
            self.build_failed.emit(project_name, message)
            self._notify_build_failure(project_id, project_name, message)

    def _notify_build_failure(self, project_id: int, project_name: str, message: str) -> None:
        worker = _BuildFailureNotifyWorker(self._services, project_id, project_name, message)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.start()

    def _on_finished(self) -> None:
        self._batch_running = False
