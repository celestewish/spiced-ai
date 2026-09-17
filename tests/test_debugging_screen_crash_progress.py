"""DebuggingScreen's crash-analysis flow: Live Task Progress Transparency.

Unity Alpha Readiness Spec, Priority 2 -- the flagship "paste a crash log,
get an AI-written fix" flow had no step feedback before the AI response
started streaming in. Same pattern as the existing Dev Docs streaming
coverage (test_debugging_screen_dev_docs_streaming.py) and the
_ProjectHealthScanWorker progress wiring this borrows from.

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching every other screen test.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.core.debugging import SOURCE_PASTE  # noqa: E402
from spiced.ui.screens.debugging import DebuggingScreen, _CrashWorker  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def test_crash_worker_declares_a_progress_signal():
    assert hasattr(_CrashWorker, "progress")


def test_crash_worker_emits_reading_and_contacting_steps(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    services.set_provider_name("mock")  # never hit a real AI provider

    worker = _CrashWorker(services, "NullReferenceException at Foo.cs:12", SOURCE_PASTE, None)
    steps: list[str] = []
    worker.progress.connect(steps.append)
    worker.run()

    assert steps[0] == "Reading the log…"
    assert steps[1].startswith("Contacting ")
    assert "Mock" in steps[1] or "mock" in steps[1]
    services.close()


def test_analyze_resets_and_populates_the_progress_trail(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    services.set_provider_name("mock")

    screen = DebuggingScreen(services)
    try:
        # Stale content from a hypothetical earlier run -- reset() at the
        # start of _on_analyze should clear this, not leave it stacked
        # underneath the new run's steps.
        screen._analysis_progress_trail.add_step("stale step from a previous run")

        screen._log_input.setPlainText("NullReferenceException at Foo.cs:12")
        screen._on_analyze()

        deadline = 0
        while screen._active_threads and deadline < 200:
            QApplication.processEvents()
            deadline += 1

        steps = screen._analysis_progress_trail.steps()
        assert "stale step from a previous run" not in steps
        assert steps[0] == "Reading the log…"
    finally:
        services.close()


def test_progress_trail_is_hidden_before_first_analysis(tmp_path):
    # The screen is never .show()n in this headless test -- isVisible()
    # would read False regardless of ProgressTrail's own setVisible() calls
    # since it factors in ancestor visibility. isHidden() reflects only
    # this widget's own explicit hidden flag, set in ProgressTrail.__init__.
    screen = DebuggingScreen(_services(tmp_path))
    assert screen._analysis_progress_trail.isHidden() is True
