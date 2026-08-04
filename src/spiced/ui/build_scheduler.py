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
surfaced, via ``build_failed`` (the Context Panel listens for this).
"""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from spiced.app.services import Services
from spiced.core.build_pipeline import BuildNotEnabledError, BuildUnavailableError
from spiced.storage.build_reports import TRIGGER_SCHEDULED

# Once a minute is plenty of resolution for a "HH:MM" schedule.
_CHECK_INTERVAL_MS = 60_000


class _ScheduledBuildWorker(QObject):
    build_done = Signal(str, bool, str)  # project_name, succeeded, message
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
                report = self._services.run_build(project, trigger=TRIGGER_SCHEDULED)
            except (BuildNotEnabledError, BuildUnavailableError) as exc:
                self.build_done.emit(project.name, False, str(exc))
                continue
            except Exception as exc:  # surfaced calmly; never crashes the app
                self.build_done.emit(project.name, False, f"Something went wrong: {exc}")
                continue
            if report.succeeded:
                self.build_done.emit(project.name, True, "")
            else:
                message = report.log_tail or "The scheduled build did not succeed."
                self.build_done.emit(project.name, False, message)
        self.finished.emit()


class BuildScheduler(QObject):
    """Owns the QTimer that checks every project's nightly build schedule."""

    build_failed = Signal(str, str)  # project_name, message
    build_report_saved = Signal()

    def __init__(self, services: Services, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._last_fired: dict[int, date] = {}
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(_CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._check_due_projects)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _check_due_projects(self) -> None:
        if self._thread is not None:
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
        self._thread = QThread()
        self._worker = _ScheduledBuildWorker(self._services, project_ids)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.build_done.connect(self._on_build_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_build_done(self, project_name: str, succeeded: bool, message: str) -> None:
        self.build_report_saved.emit()
        if not succeeded:
            self.build_failed.emit(project_name, message)

    def _on_finished(self) -> None:
        self._thread = None
        self._worker = None
