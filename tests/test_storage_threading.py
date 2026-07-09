"""Regression tests: storage must be usable from a background thread.

Chat/provider work runs off the UI thread and then records prompt usage, which
previously crashed with "SQLite objects created in a thread can only be used in
that same thread."
"""

import threading

from spiced.app.services import Services


def _run_in_thread(fn):
    error: list[BaseException] = []

    def target():
        try:
            fn()
        except BaseException as exc:  # capture to re-raise on the main thread
            error.append(exc)

    t = threading.Thread(target=target)
    t.start()
    t.join()
    if error:
        raise error[0]


def test_record_usage_from_another_thread(tmp_path):
    services = Services(tmp_path / "spiced.db")
    try:
        _run_in_thread(lambda: services.usage.record_prompt("openai", kind="test"))
        assert services.usage.status().used == 1
    finally:
        services.close()


def test_create_project_from_another_thread(tmp_path):
    services = Services(tmp_path / "spiced.db")
    try:
        _run_in_thread(lambda: services.projects.create_project("Threaded", "Unity"))
        assert [p.name for p in services.projects.list_projects()] == ["Threaded"]
    finally:
        services.close()


def test_usage_persists_across_connections(tmp_path):
    db_file = tmp_path / "spiced.db"
    first = Services(db_file)
    first.usage.record_prompt("openai")
    first.close()

    second = Services(db_file)
    try:
        assert second.usage.status().used == 1
    finally:
        second.close()
