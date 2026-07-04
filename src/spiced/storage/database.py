"""SQLite connection management and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

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
    """Owns a single SQLite connection and initializes the schema."""

    def __init__(self, path: str | Path | None = None) -> None:
        # ":memory:" is honored directly; otherwise fall back to the default.
        if path is None:
            path = default_db_path()
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
