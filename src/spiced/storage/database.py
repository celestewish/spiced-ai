"""SQLite connection management and schema initialization.

Spiced runs provider/chat work on a background thread, so database access can
come from more than one thread. sqlite3 forbids sharing a connection across
threads unless you opt in *and* serialize access yourself. We do exactly that:
the connection is opened with ``check_same_thread=False`` and every read/write
goes through a re-entrant lock, so calls are serialized and never overlap.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    engine      TEXT NOT NULL DEFAULT 'Unity',
    path        TEXT,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS prompt_usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    provider   TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'chat',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def default_db_path() -> Path:
    """Return the default per-user database location.

    Uses a hidden application folder in the user's home directory so the
    database survives across runs without polluting the working directory.
    """
    base = Path.home() / ".spiced"
    base.mkdir(parents=True, exist_ok=True)
    return base / "spiced.db"


class Database:
    """Owns a single SQLite connection and serializes access across threads."""

    def __init__(self, path: str | Path | None = None) -> None:
        # ":memory:" is honored directly; otherwise fall back to the default.
        if path is None:
            path = default_db_path()
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        """Run a write statement, commit, and return the new row id."""
        with self._lock:
            cur = self.conn.execute(sql, tuple(params or ()))
            self.conn.commit()
            return int(cur.lastrowid)

    def query_one(self, sql: str, params: Sequence[Any] | None = None) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, tuple(params or ())).fetchone()

    def query_all(self, sql: str, params: Sequence[Any] | None = None) -> Iterable[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, tuple(params or ())).fetchall()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
