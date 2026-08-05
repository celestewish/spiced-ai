"""Store Page Optimization Advisor persistence.

One row per reviewed Steam/itch store page draft (title/description/tags the
developer pasted or imported) plus the AI's suggestions-only review. Never a
guarantee of sales, never published anywhere by Spiced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class StorePageReview:
    id: int
    project_id: int
    title: str | None
    description: str | None
    tags_json: str | None
    ai_summary: str | None
    provider: str | None
    created_at: str

    @property
    def tags(self) -> list[str]:
        if not self.tags_json:
            return []
        try:
            data = json.loads(self.tags_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return data if isinstance(data, list) else []


class StorePageReviewRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        title: str | None,
        description: str | None,
        tags_json: str | None,
        ai_summary: str | None,
        provider: str | None,
    ) -> StorePageReview:
        new_id = self._db.execute(
            "INSERT INTO store_page_reviews "
            "(project_id, title, description, tags_json, ai_summary, provider) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, title, description, tags_json, ai_summary, provider),
        )
        return self.get(new_id)

    def get(self, review_id: int) -> StorePageReview:
        row = self._db.query_one("SELECT * FROM store_page_reviews WHERE id = ?", (review_id,))
        if row is None:
            raise KeyError(f"No store page review with id {review_id}")
        return self._to_review(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[StorePageReview]:
        rows = self._db.query_all(
            "SELECT * FROM store_page_reviews WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_review(r) for r in rows]

    @staticmethod
    def _to_review(row) -> StorePageReview:
        return StorePageReview(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"],
            tags_json=row["tags_json"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
