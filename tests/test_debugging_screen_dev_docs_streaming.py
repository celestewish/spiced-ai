"""DebuggingScreen's "Regenerate docs" button: streaming AI response wiring.

Dev Docs used to be the app's one demonstration of PillButton's
indeterminate water-fill loading (Frutiger Aero pass 5/5) -- it's now the
first (and, once the rest of the rollout lands, one of many) screen using
real token streaming instead, since growing visible text is a stronger
"still working" signal than an indeterminate animation for a plain
request/response AI call. See ai.base.AIProvider.generate_stream and
ui.thread_utils.AIStreamWorker.

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching the pattern used by the other screen tests.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.screens.debugging import DebuggingScreen, _DevDocsWorker  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def _fake_result() -> SimpleNamespace:
    return SimpleNamespace(
        scan=SimpleNamespace(file_count=3, class_count=2, method_count=7),
        response_text="Looks tidy.",
    )


def test_dev_docs_button_does_not_use_water_fill(tmp_path):
    """Streaming text now serves the "still alive" role water-fill used to
    -- Dev Docs shouldn't carry both a growing-text signal and an
    indeterminate animation at once."""
    screen = DebuggingScreen(_services(tmp_path))
    assert screen._dev_docs_btn._water_fill_enabled is False


def test_generate_disables_the_button_and_clears_the_result_immediately(tmp_path):
    services = _services(tmp_path)
    services.set_provider_name("mock")  # never hit a real AI provider
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)

    screen = DebuggingScreen(services)
    try:
        screen._on_dev_docs_generate()

        # thread.start() is non-blocking -- these are the click handler's
        # own synchronous side effects, set before the worker thread (which
        # will shortly fail fast with "no Unity folder connected", since
        # this project has none) ever runs.
        assert screen._dev_docs_btn.isEnabled() is False
        assert screen._dev_docs_btn.text() == "Generating…"
        assert screen._dev_docs_result.toPlainText() == ""
    finally:
        # Let the real (fast, offline, no-unity-folder) worker finish
        # rather than leaving a QThread running past the test.
        deadline = 0
        while screen._active_threads and deadline < 200:
            QApplication.processEvents()
            deadline += 1
        services.close()


def test_chunk_appends_text_incrementally(tmp_path):
    screen = DebuggingScreen(_services(tmp_path))
    screen._dev_docs_result.clear()

    screen._on_dev_docs_chunk("Hello ")
    screen._on_dev_docs_chunk("world")

    assert screen._dev_docs_result.toPlainText() == "Hello world"


def test_done_replaces_any_partial_streamed_text_and_restores_the_button(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = DebuggingScreen(services)
    screen._dev_docs_btn.setEnabled(False)
    screen._dev_docs_btn.setText("Generating…")
    screen._on_dev_docs_chunk("Looks ti")  # partial text from mid-stream

    screen._on_dev_docs_done(_fake_result())

    assert screen._dev_docs_btn.isEnabled() is True
    assert screen._dev_docs_btn.text() == "Regenerate docs"
    assert "Looks tidy." in screen._dev_docs_result.toPlainText()
    assert "Looks ti\n" not in screen._dev_docs_result.toPlainText()
    services.close()


def test_worker_call_plumbs_on_chunk_through_to_dev_docs_generate(tmp_path):
    """Smoke test that _DevDocsWorker._call actually forwards the streaming
    callback to services.dev_docs.generate, not just that the base class
    mechanics (covered in test_thread_utils.py) work in isolation."""
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths", path=str(tmp_path))
    services.set_active_project(project.id)

    captured: dict = {}
    real_generate = services.dev_docs.generate

    def _spy_generate(provider, project, *, record_usage=None, on_chunk=None):
        captured["on_chunk"] = on_chunk
        return real_generate(provider, project, record_usage=record_usage, on_chunk=on_chunk)

    services.dev_docs.generate = _spy_generate
    services.set_provider_name("mock")

    worker = _DevDocsWorker(services, project)
    chunks: list[str] = []
    worker.chunk.connect(chunks.append)
    worker.run()

    assert captured["on_chunk"] is not None
    assert len(chunks) > 0
    services.close()


def test_failed_restores_the_button_and_shows_the_message(tmp_path):
    services = _services(tmp_path)
    screen = DebuggingScreen(services)
    screen._dev_docs_btn.setEnabled(False)
    screen._dev_docs_btn.setText("Generating…")
    screen._on_dev_docs_chunk("partial text")

    screen._on_dev_docs_failed("Connect a Unity folder for this project first.")

    assert screen._dev_docs_btn.isEnabled() is True
    assert screen._dev_docs_btn.text() == "Regenerate docs"
    assert screen._dev_docs_result.toPlainText() == "Connect a Unity folder for this project first."
    services.close()
