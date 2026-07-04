"""Prompt-usage persistence (local counter)."""

from __future__ import annotations

from spiced.storage.database import Database


class UsageRepository:
    """Records and counts prompt usage. Purely local; no billing."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, provider: str, kind: str = "chat") -> None:
        self._db.conn.execute(
            "INSERT INTO prompt_usage (provider, kind) VALUES (?, ?)",
            (provider, kind),
        )
        self._db.conn.commit()

    def total(self) -> int:
        row = self._db.conn.execute("SELECT COUNT(*) AS n FROM prompt_usage").fetchone()
        return int(row["n"])
