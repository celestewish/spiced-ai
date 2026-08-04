"""Tests for ui.screens.testing._BuildWorker: the manual "Run build" button's
worker for the Automated Build Pipeline.

No display is available in this environment, so this uses Qt's offscreen
platform plugin (same approach as test_build_scheduler.py) to construct a
real QObject headlessly, and calls ``run()`` directly rather than going
through a QThread.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.storage.build_reports import TRIGGER_MANUAL, BuildReport  # noqa: E402
from spiced.ui.screens.testing import _BuildWorker  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def _fake_report() -> BuildReport:
    return BuildReport(
        id=1,
        project_id=1,
        trigger=TRIGGER_MANUAL,
        target_platform="StandaloneWindows64",
        started_at="2026-01-01 02:00:00",
        finished_at="2026-01-01 02:05:00",
        succeeded=True,
        log_tail=None,
        output_path=None,
        marked_stable=False,
        created_at="2026-01-01 02:05:00",
    )


def test_build_worker_passes_project_editor_override_through_to_run_build(monkeypatch, tmp_path):
    """Bug fix: the manual "Run build" button used to call ``run_build``
    without the project's configured Unity Editor path override, even
    though Run Unity Tests' own worker already passed it through -- the two
    features silently disagreed about which Unity Editor to use."""
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.projects.set_unity_test_run_settings(project.id, True, "/custom/Unity.exe")
    project = services.projects.get_project(project.id)

    captured = {}

    def fake_run_build(project, trigger, target_platform=None, editor_override=None):
        captured["editor_override"] = editor_override
        captured["target_platform"] = target_platform
        return _fake_report()

    monkeypatch.setattr(services, "run_build", fake_run_build)

    worker = _BuildWorker(services, project, "StandaloneWindows64")
    done = []
    worker.done.connect(done.append)
    worker.run()

    assert captured["editor_override"] == "/custom/Unity.exe"
    assert captured["target_platform"] == "StandaloneWindows64"
    assert len(done) == 1


def test_build_worker_passes_none_when_no_override_configured(monkeypatch, tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")

    captured = {}

    def fake_run_build(project, trigger, target_platform=None, editor_override=None):
        captured["editor_override"] = editor_override
        return _fake_report()

    monkeypatch.setattr(services, "run_build", fake_run_build)

    worker = _BuildWorker(services, project, "StandaloneWindows64")
    worker.run()

    assert captured["editor_override"] is None
