"""Key/value application settings persistence."""

from __future__ import annotations

from spiced.storage.database import Database


class SettingsRepository:
    """Simple string key/value store backed by the app_settings table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self._db.query_one("SELECT value FROM app_settings WHERE key = ?", (key,))
        return row["value"] if row is not None else default

    def set(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
