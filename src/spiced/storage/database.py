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

CREATE TABLE IF NOT EXISTS debug_sessions (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id                INTEGER NOT NULL,
    source_type               TEXT NOT NULL,
    source_filename           TEXT,
    detected_error_type       TEXT,
    detected_file             TEXT,
    detected_line             INTEGER,
    raw_excerpt               TEXT,
    summary                   TEXT,
    suggested_next_steps_json TEXT,
    provider                  TEXT,
    created_at                TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_cases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'General',
    priority        TEXT NOT NULL DEFAULT 'Medium',
    steps           TEXT,
    expected_result TEXT,
    status          TEXT NOT NULL DEFAULT 'Not Run',
    failure_note    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id            INTEGER NOT NULL,
    source_type           TEXT NOT NULL,
    source_filename       TEXT,
    raw_excerpt           TEXT,
    parsed_summary_json   TEXT,
    ai_summary            TEXT,
    retest_checklist_json TEXT,
    provider              TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns added after Phase 0. Applied idempotently so existing databases and
# their project rows keep working; missing values default safely to NULL.
PROJECT_MIGRATIONS = {
    "validation_status": "TEXT",
    "engine_metadata_json": "TEXT",
}


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
            self._migrate_projects()
            self.conn.commit()

    def _migrate_projects(self) -> None:
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(projects)")}
        for column, col_type in PROJECT_MIGRATIONS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE projects ADD COLUMN {column} {col_type}")

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
