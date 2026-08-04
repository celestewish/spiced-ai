"""Tests for ui.thread_utils.launch_worker.

Covers the fix for the "single shared ``self._thread`` attribute" crash:
every ``_start_*``-style method on a screen used to do
``self._thread = QThread()``, so a second action starting while an earlier
one was still running on the *same screen instance* would reassign the
attribute and drop the only Python reference to the still-running
``QThread``. Once garbage-collected mid-run, PySide6/Qt aborts the process
("QThread: Destroyed while thread is still running"). ``launch_worker``
fixes this by tracking every in-flight (thread, worker) pair in list
attributes on the owner until each one finishes.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication, QObject, Signal

from spiced.ui.thread_utils import launch_worker


class _DummyWorker(QObject):
    done = Signal()


class _Owner:
    """Stand-in for a screen instance -- just needs to be a plain object
    `launch_worker` can attach `_active_threads`/`_active_workers` to."""


def test_launch_worker_creates_tracking_lists_on_first_use():
    owner = _Owner()
    assert not hasattr(owner, "_active_threads")
    assert not hasattr(owner, "_active_workers")

    launch_worker(owner, _DummyWorker())

    assert hasattr(owner, "_active_threads")
    assert hasattr(owner, "_active_workers")


def test_launch_worker_tracks_multiple_in_flight_threads_and_workers():
    """Simulates two different actions on the same screen starting before
    either finishes -- exactly the scenario that used to crash when a
    single ``self._thread`` attribute got reassigned out from under a
    still-running QThread."""
    owner = _Owner()
    worker_a = _DummyWorker()
    worker_b = _DummyWorker()

    thread_a = launch_worker(owner, worker_a)
    thread_b = launch_worker(owner, worker_b)

    assert thread_a is not thread_b
    assert owner._active_threads == [thread_a, thread_b]
    assert owner._active_workers == [worker_a, worker_b]

    # Both threads must still be valid, live objects -- not just the most
    # recently created one, which is exactly what a shared self._thread
    # attribute would have left after the second assignment clobbered it.
    assert thread_a.isRunning() is False
    assert thread_b.isRunning() is False


def test_launch_worker_cleanup_only_removes_the_thread_that_finished():
    owner = _Owner()
    worker_a = _DummyWorker()
    worker_b = _DummyWorker()
    thread_a = launch_worker(owner, worker_a)
    thread_b = launch_worker(owner, worker_b)

    # Simulate thread_a finishing while thread_b is still in flight.
    thread_a.finished.emit()

    assert thread_a not in owner._active_threads
    assert worker_a not in owner._active_workers
    assert thread_b in owner._active_threads
    assert worker_b in owner._active_workers


class _SlowWorker(QObject):
    done = Signal(int)

    def __init__(self, value: int, delay: float) -> None:
        super().__init__()
        self._value = value
        self._delay = delay

    def run(self) -> None:
        time.sleep(self._delay)
        self.done.emit(self._value)


def test_launch_worker_runs_two_real_concurrent_threads_to_completion():
    """End-to-end: two different worker threads started back-to-back, before
    either finishes, on the same owner -- both must run to completion and
    report their result. This is the actual bug repro: with the old
    ``self._thread = QThread()`` pattern, starting a second action while the
    first was still running would drop the first thread's only reference
    and crash the process; here both must survive and finish.
    """
    app = QCoreApplication.instance() or QCoreApplication([])
    owner = _Owner()
    results: list[int] = []

    worker_a = _SlowWorker(1, 0.2)
    thread_a = launch_worker(owner, worker_a)
    thread_a.started.connect(worker_a.run)
    worker_a.done.connect(results.append)
    worker_a.done.connect(thread_a.quit)

    worker_b = _SlowWorker(2, 0.05)
    thread_b = launch_worker(owner, worker_b)
    thread_b.started.connect(worker_b.run)
    worker_b.done.connect(results.append)
    worker_b.done.connect(thread_b.quit)

    thread_a.start()
    thread_b.start()

    deadline = time.time() + 5
    while owner._active_threads and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert sorted(results) == [1, 2]
    assert owner._active_threads == []
    assert owner._active_workers == []
