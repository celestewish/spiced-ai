"""Wishlist/Analytics Summary persistence.

One row per pasted/imported analytics snapshot (see core.wishlist_analytics
for the documented ``metric,value`` CSV format). Each new import is diffed
against the most recent previous import for the same project.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class WishlistAnalyticsImport:
    id: int
    project_id: int
    metrics_json: str
    raw_excerpt: str | None
    source_filename: str | None
    created_at: str

    @property
    def metrics(self) -> dict[str, str]:
        try:
            data = json.loads(self.metrics_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}


class WishlistAnalyticsImportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        metrics_json: str,
        raw_excerpt: str | None = None,
        source_filename: str | None = None,
    ) -> WishlistAnalyticsImport:
        new_id = self._db.execute(
            "INSERT INTO wishlist_analytics_imports "
            "(project_id, metrics_json, raw_excerpt, source_filename) VALUES (?, ?, ?, ?)",
            (project_id, metrics_json, raw_excerpt, source_filename),
        )
        return self.get(new_id)

    def get(self, import_id: int) -> WishlistAnalyticsImport:
        row = self._db.query_one(
            "SELECT * FROM wishlist_analytics_imports WHERE id = ?", (import_id,)
        )
        if row is None:
            raise KeyError(f"No wishlist analytics import with id {import_id}")
        return self._to_import(row)

    def latest_for_project(self, project_id: int) -> WishlistAnalyticsImport | None:
        row = self._db.query_one(
            "SELECT * FROM wishlist_analytics_imports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (project_id,),
        )
        return self._to_import(row) if row is not None else None

    def list_for_project(self, project_id: int, limit: int = 20) -> list[WishlistAnalyticsImport]:
        rows = self._db.query_all(
            "SELECT * FROM wishlist_analytics_imports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_import(r) for r in rows]

    @staticmethod
    def _to_import(row) -> WishlistAnalyticsImport:
        return WishlistAnalyticsImport(
            id=row["id"],
            project_id=row["project_id"],
            metrics_json=row["metrics_json"],
            raw_excerpt=row["raw_excerpt"],
            source_filename=row["source_filename"],
            created_at=row["created_at"],
        )
