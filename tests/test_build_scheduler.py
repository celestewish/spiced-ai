"""Tests for the in-app QTimer-based nightly build scheduler.

No display is available in this environment, so this uses Qt's offscreen
platform plugin (same approach as test_source_link_widget.py) to construct
real QObjects headlessly. The real QTimer is never allowed to actually fire
during a test — ``_check_due_projects``/``_ScheduledBuildWorker.run`` are
called directly so scheduling logic is exercised deterministically without
depending on an active Qt event loop or wall-clock timing.
"""

from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.core.build_pipeline import BuildNotEnabledError  # noqa: E402
from spiced.storage.build_reports import BuildReport  # noqa: E402
from spiced.ui import build_scheduler as scheduler_module  # noqa: E402
from spiced.ui.build_scheduler import BuildScheduler, _ScheduledBuildWorker  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


class _FixedClock:
    """A stand-in for ``datetime`` whose ``now()`` is pinned for a test."""

    _now = datetime(2026, 1, 1, 2, 0, 0)

    @classmethod
    def now(cls):
        return cls._now


def _fake_report(succeeded: bool, log_tail: str | None = None) -> BuildReport:
    return BuildReport(
        id=1,
        project_id=1,
        trigger="scheduled",
        target_platform="StandaloneWindows64",
        started_at="2026-01-01 02:00:00",
        finished_at="2026-01-01 02:05:00",
        succeeded=succeeded,
        log_tail=log_tail,
        output_path=None,
        marked_stable=False,
        created_at="2026-01-01 02:05:00",
    )


# --- _ScheduledBuildWorker (direct, synchronous call — no QThread needed) ----


def test_worker_stays_quiet_on_success(monkeypatch, tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    monkeypatch.setattr(
        services,
        "run_build",
        lambda project, trigger, editor_override=None: _fake_report(True),
    )

    worker = _ScheduledBuildWorker(services, [project.id])
    calls = []
    worker.build_done.connect(lambda name, ok, msg: calls.append((name, ok, msg)))
    worker.run()

    assert calls == [(project.name, True, "")]


def test_worker_reports_failure_with_log_tail(monkeypatch, tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    monkeypatch.setattr(
        services,
        "run_build",
        lambda project, trigger, editor_override=None: _fake_report(False, "boom: NRE"),
    )

    worker = _ScheduledBuildWorker(services, [project.id])
    calls = []
    worker.build_done.connect(lambda name, ok, msg: calls.append((name, ok, msg)))
    worker.run()

    assert len(calls) == 1
    name, ok, message = calls[0]
    assert name == project.name
    assert ok is False
    assert "boom: NRE" in message


def test_worker_handles_gate_error_without_crashing(monkeypatch, tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")

    def raise_not_enabled(project, trigger, editor_override=None):
        raise BuildNotEnabledError("not enabled")

    monkeypatch.setattr(services, "run_build", raise_not_enabled)

    worker = _ScheduledBuildWorker(services, [project.id])
    calls = []
    worker.build_done.connect(lambda name, ok, msg: calls.append((name, ok, msg)))
    finished = []
    worker.finished.connect(lambda: finished.append(True))
    worker.run()

    assert calls == [(project.name, False, "not enabled")]
    assert finished == [True]


def test_worker_skips_projects_that_no_longer_exist(tmp_path):
    services = _services(tmp_path)
    worker = _ScheduledBuildWorker(services, [999])
    calls = []
    worker.build_done.connect(lambda name, ok, msg: calls.append((name, ok, msg)))
    worker.run()
    assert calls == []


def test_worker_passes_project_editor_override_through_to_run_build(monkeypatch, tmp_path):
    """Bug fix: the scheduled build path used to call ``run_build`` without
    the project's configured Unity Editor path override, so Automated Build
    Pipeline silently ignored it even though Run Unity Tests honored it."""
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.projects.set_unity_test_run_settings(project.id, True, "/custom/Unity.exe")
    project = services.projects.get_project(project.id)

    captured = {}

    def fake_run_build(project, trigger, editor_override=None):
        captured["editor_override"] = editor_override
        return _fake_report(True)

    monkeypatch.setattr(services, "run_build", fake_run_build)

    worker = _ScheduledBuildWorker(services, [project.id])
    worker.run()

    assert captured["editor_override"] == "/custom/Unity.exe"


# --- BuildScheduler due-project detection ------------------------------------


def test_check_due_projects_fires_only_fully_opted_in_and_scheduled(monkeypatch, tmp_path):
    services = _services(tmp_path)
    due = services.projects.create_project("Due")
    services.projects.set_build_pipeline_settings(due.id, True, "StandaloneWindows64")
    services.projects.set_build_schedule(due.id, True, "02:00")

    pipeline_off = services.projects.create_project("PipelineOff")
    services.projects.set_build_schedule(pipeline_off.id, True, "02:00")

    schedule_off = services.projects.create_project("ScheduleOff")
    services.projects.set_build_pipeline_settings(schedule_off.id, True, "StandaloneWindows64")

    wrong_time = services.projects.create_project("WrongTime")
    services.projects.set_build_pipeline_settings(wrong_time.id, True, "StandaloneWindows64")
    services.projects.set_build_schedule(wrong_time.id, True, "09:30")

    monkeypatch.setattr(scheduler_module, "datetime", _FixedClock)
    scheduler = BuildScheduler(services)
    scheduler.stop()
    started_batches = []
    monkeypatch.setattr(scheduler, "_start_batch", started_batches.append)

    scheduler._check_due_projects()

    assert started_batches == [[due.id]]


def test_check_due_projects_does_not_refire_same_day(monkeypatch, tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Due")
    services.projects.set_build_pipeline_settings(project.id, True, "StandaloneWindows64")
    services.projects.set_build_schedule(project.id, True, "02:00")

    monkeypatch.setattr(scheduler_module, "datetime", _FixedClock)
    scheduler = BuildScheduler(services)
    scheduler.stop()
    started_batches = []
    monkeypatch.setattr(scheduler, "_start_batch", started_batches.append)

    scheduler._check_due_projects()
    scheduler._check_due_projects()

    assert started_batches == [[project.id]]


def test_check_due_projects_waits_while_a_batch_is_already_running(monkeypatch, tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Due")
    services.projects.set_build_pipeline_settings(project.id, True, "StandaloneWindows64")
    services.projects.set_build_schedule(project.id, True, "02:00")

    monkeypatch.setattr(scheduler_module, "datetime", _FixedClock)
    scheduler = BuildScheduler(services)
    scheduler.stop()
    started_batches = []
    monkeypatch.setattr(scheduler, "_start_batch", started_batches.append)
    scheduler._batch_running = True  # simulate a batch already in flight

    scheduler._check_due_projects()

    assert started_batches == []
