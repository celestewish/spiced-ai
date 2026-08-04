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
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread


def launch_worker(owner: Any, worker: QObject) -> QThread:
    """Move `worker` onto a new `QThread` and keep both alive on `owner`
    until the thread finishes.

    Returns the new thread. The caller is still responsible for connecting
    `worker`'s own `done`/`failed` (or equivalent) signals to its UI-update
    slots and to `thread.quit`, and for calling `thread.start()` -- this
    helper only owns the thread/worker's lifetime, not their outcome.
    """
    if not hasattr(owner, "_active_threads"):
        owner._active_threads = []
    if not hasattr(owner, "_active_workers"):
        owner._active_workers = []

    thread = QThread()
    worker.moveToThread(thread)
    owner._active_threads.append(thread)
    owner._active_workers.append(worker)

    def _cleanup() -> None:
        if thread in owner._active_threads:
            owner._active_threads.remove(thread)
        if worker in owner._active_workers:
            owner._active_workers.remove(worker)

    thread.finished.connect(_cleanup)
    return thread
