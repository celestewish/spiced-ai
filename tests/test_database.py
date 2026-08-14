"""Database connection health: opening the local SQLite file must fail
loudly and clearly, never with a bare, unactionable sqlite3 traceback.

Regression coverage for a real gap: ``Database.__init__`` used to call
``sqlite3.connect`` with no error handling at all. Since every screen shares
one ``Services.db``/``Database`` instance and MainWindow builds every screen
eagerly with no per-screen isolation, a locked file (another Spiced window
already open), a permissions problem, or a full disk would crash the whole
app before any window ever showed -- which is exactly the shape of a "the
app/a page just fails to load, with a database error" report.
"""

from __future__ import annotations

import sqlite3

import pytest

from spiced.storage.database import Database, DatabaseUnavailableError


def test_opens_a_normal_path_fine(tmp_path):
    db = Database(tmp_path / "spiced.db")
    try:
        assert db.query_one("SELECT 1 AS one")["one"] == 1
    finally:
        db.close()


def test_missing_parent_directory_raises_a_clear_actionable_error(tmp_path):
    unreachable_path = tmp_path / "does-not-exist" / "spiced.db"

    with pytest.raises(DatabaseUnavailableError) as excinfo:
        Database(unreachable_path)

    message = str(excinfo.value)
    assert str(unreachable_path) in message
    # Actionable for a non-technical reader, not just the raw sqlite3 text.
    assert "permission" in message.lower() or "already have it open" in message.lower()


def test_wraps_the_original_sqlite_error_as_the_cause(tmp_path):
    unreachable_path = tmp_path / "does-not-exist" / "spiced.db"

    with pytest.raises(DatabaseUnavailableError) as excinfo:
        Database(unreachable_path)

    assert isinstance(excinfo.value.__cause__, sqlite3.Error)


def test_a_directory_in_place_of_a_file_also_raises_the_clear_error(tmp_path):
    directory_path = tmp_path / "spiced.db"
    directory_path.mkdir()

    with pytest.raises(DatabaseUnavailableError):
        Database(directory_path)
