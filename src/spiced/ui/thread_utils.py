"""Shared helper for launching QThread-backed workers from a UI screen.

Every screen with an AI or long-running action follows the same shape: build
a worker `QObject`, move it to a new `QThread`, wire up signals, start it.
Assigning that thread/worker to a single shared `self._thread`/`self._worker`
attribute is a bug the moment a screen has more than one such action: if a
second action starts while an earlier one is still running on the same
screen instance, reassigning the attribute drops the only Python reference
to the still-running `QThread`. Once it's garbage-collected while its OS
thread is still active, PySide6/Qt aborts the process ("QThread: Destroyed
while thread is still running") -- a hard crash, not a catchable exception.

`launch_worker` fixes this by keeping a strong reference to *every*
in-flight (thread, worker) pair on the owner, in list attributes it creates
on first use, until each one actually finishes -- so any number of actions
can run concurrently on the same screen without clobbering each other.

Live Task Progress Transparency (Phase L, deferred from Phase K, Core tier):
a worker MAY optionally declare its own ``progress = Signal(str)`` and emit
plain-language step descriptions while it runs (e.g. "Running EditMode
tests…", not a numeric percentage -- see ``ui.widgets.progress_trail`` for
why). ``launch_worker`` stays a thin, generic connector: pass
``progress_slot=some_trail.add_step`` (or any ``Callable[[str], None]``) and,
*if* the worker has a ``progress`` signal, it's connected automatically. A
worker with no ``progress`` signal, or a caller that doesn't pass
``progress_slot``, behaves exactly as before this feature existed --
``hasattr`` degrades to a silent no-op rather than raising, so every one of
this app's 40+ existing call sites keeps working unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal


def launch_worker(
    owner: Any,
    worker: QObject,
    *,
    progress_slot: Callable[[str], None] | None = None,
) -> QThread:
    """Move `worker` onto a new `QThread` and keep both alive on `owner`
    until the thread finishes.

    Returns the new thread. The caller is still responsible for connecting
    `worker`'s own `done`/`failed` (or equivalent) signals to its UI-update
    slots and to `thread.quit`, and for calling `thread.start()` -- this
    helper only owns the thread/worker's lifetime, not their outcome.

    ``progress_slot``, if given, is connected to ``worker.progress`` when
    that signal exists (see the module docstring) -- entirely optional and
    fully backward-compatible with workers/call sites that don't use it.
    """
    if not hasattr(owner, "_active_threads"):
        owner._active_threads = []
    if not hasattr(owner, "_active_workers"):
        owner._active_workers = []

    thread = QThread()
    worker.moveToThread(thread)
    owner._active_threads.append(thread)
    owner._active_workers.append(worker)

    if progress_slot is not None and hasattr(worker, "progress"):
        worker.progress.connect(progress_slot)

    def _cleanup() -> None:
        if thread in owner._active_threads:
            owner._active_threads.remove(thread)
        if worker in owner._active_workers:
            owner._active_workers.remove(worker)

    thread.finished.connect(_cleanup)
    return thread


class AIStreamWorker(QObject):
    """Shared base for the app's "one opaque AI call" workers -- the ones
    that call a single ``core.*.generate(provider, ..., on_chunk=...)``
    helper and report back via exactly the ``done``/``failed`` pair every
    such worker has always had, now with a ``chunk`` signal alongside for
    streamed partial text.

    Subclasses implement ``_call(on_chunk)`` (build the provider, call the
    right ``core.*.generate`` helper, return its typed result) and, if their
    core call can raise feature-specific exceptions the user should see a
    plain message for rather than "Something went wrong", override
    ``expected_errors``/``error_message``. This centralizes the
    chunk-signal wiring and the try/except shape that used to be
    hand-duplicated in each worker's own ``run()``.
    """

    chunk = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def _call(self, on_chunk: Callable[[str], None]) -> Any:
        raise NotImplementedError

    def expected_errors(self) -> tuple[type[Exception], ...]:
        """Exception types with a message worth showing the user as-is."""
        return ()

    def error_message(self, exc: Exception) -> str:
        return f"Something went wrong: {exc}"

    def run(self) -> None:
        try:
            result = self._call(self.chunk.emit)
            self.done.emit(result)
        except self.expected_errors() as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(self.error_message(exc))
