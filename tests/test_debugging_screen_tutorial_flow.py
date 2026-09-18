"""DebuggingScreen's tutorial-mode analysis: the Analyze step runs through
MockProvider (via ``_CrashWorker``'s ``provider_override``) instead of the
developer's own ``Services.build_provider()``/``provider_name()`` setting,
and ``analysis_finished`` fires on the worker's real ``done`` (and
``failed``) signal so the first-launch tutorial's auto-advance has
something real to connect to.

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching the pattern used by the other Debugging Buddy
tests (e.g. test_debugging_screen_crash_progress.py, whose thread-polling
pattern this reuses).
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.ai.mock_provider import MockProvider  # noqa: E402
from spiced.app.services import Services  # noqa: E402
from spiced.core.debugging import SOURCE_PASTE  # noqa: E402
from spiced.ui.screens.debugging import DebuggingScreen, _CrashWorker  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def _pump_until_idle(screen, deadline: int = 500) -> None:
    # A bare processEvents()-spin loop with no yield can starve the real
    # background QThread of GIL time in this environment badly enough that
    # it never gets scheduled at all -- the tiny sleep each tick is what
    # actually lets it run, not just a politeness nicety.
    ticks = 0
    while screen._active_threads and ticks < deadline:
        QApplication.processEvents()
        time.sleep(0.002)
        ticks += 1


# --- _CrashWorker: provider_override -----------------------------------------


def test_crash_worker_uses_the_override_instead_of_build_provider(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    # provider_name is left at its default ("openai", no key) -- if the
    # worker ever fell back to build_provider() instead of the override,
    # this would fail rather than quietly happening to also work.
    worker = _CrashWorker(
        services,
        "NullReferenceException at Foo.cs:12",
        SOURCE_PASTE,
        None,
        provider_override=MockProvider(),
    )
    results = []
    failures = []
    worker.done.connect(results.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == []
    assert len(results) == 1
    services.close()


# --- DebuggingScreen: set_tutorial_provider_override / _on_analyze wiring ----


def test_tutorial_override_lets_analysis_succeed_without_a_real_provider_configured(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    # Deliberately not calling services.set_provider_name("mock") --
    # proves the override bypasses build_provider() entirely rather than
    # just happening to agree with a provider that would work anyway.

    screen = DebuggingScreen(services)
    try:
        screen.set_tutorial_provider_override(MockProvider())
        screen._log_input.setPlainText("NullReferenceException at Foo.cs:12")
        screen._on_analyze()
        _pump_until_idle(screen)

        assert screen._result.toPlainText() != ""
        assert "Something went wrong" not in screen._result.toPlainText()
    finally:
        services.close()


def test_provider_override_is_cleared_immediately_so_it_never_leaks_to_the_next_analysis(
    tmp_path,
):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = DebuggingScreen(services)
    try:
        screen.set_tutorial_provider_override(MockProvider())
        screen._log_input.setPlainText("NullReferenceException at Foo.cs:12")
        screen._on_analyze()

        # Cleared synchronously inside _on_analyze, before the worker
        # thread even finishes -- a real (non-tutorial) analysis started
        # right after must never silently keep using MockProvider.
        assert screen._tutorial_provider_override is None
        _pump_until_idle(screen)
    finally:
        services.close()


def test_tutorial_analysis_never_touches_the_real_provider_name_setting(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    original_provider_name = services.provider_name()

    screen = DebuggingScreen(services)
    try:
        screen.set_tutorial_provider_override(MockProvider())
        screen._log_input.setPlainText("NullReferenceException at Foo.cs:12")
        screen._on_analyze()
        _pump_until_idle(screen)

        assert services.provider_name() == original_provider_name
    finally:
        services.close()


def test_set_tutorial_provider_override_is_a_no_op_helper_when_never_called(tmp_path):
    services = _services(tmp_path)
    screen = DebuggingScreen(services)
    assert screen._tutorial_provider_override is None
    services.close()


# --- analysis_finished: the tutorial's auto-advance signal -------------------


def test_analysis_finished_fires_after_a_successful_analysis(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = DebuggingScreen(services)
    try:
        finished = []
        screen.analysis_finished.connect(lambda: finished.append(True))
        screen.set_tutorial_provider_override(MockProvider())
        screen._log_input.setPlainText("NullReferenceException at Foo.cs:12")
        screen._on_analyze()
        _pump_until_idle(screen)

        assert finished == [True]
    finally:
        services.close()


def test_analysis_finished_also_fires_on_failure_so_a_waiting_tutorial_cannot_hang(tmp_path):
    services = _services(tmp_path)
    screen = DebuggingScreen(services)
    finished = []
    screen.analysis_finished.connect(lambda: finished.append(True))

    screen._on_failed("Something went wrong during analysis: boom")

    assert finished == [True]
    services.close()
