"""Pre-commit-review log persistence (optional history of local hook runs).

Not required for the hook itself to work — the hook (``core.precommit_check``)
always exits 0 and prints its findings to stdout/stderr whether or not this
table (or Spiced's GUI) is even reachable. This is only a convenience log so
the Projects screen can show "last run" history when the hook does have
access to the local database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class PrecommitReview:
    id: int
    project_id: int
    file_count: int
    findings_json: str | None
    created_at: str

    @property
    def findings(self) -> list:
        if not self.findings_json:
            return []
        try:
            data = json.loads(self.findings_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return data if isinstance(data, list) else []


class PrecommitReviewRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self, project_id: int, file_count: int, findings: list | None = None
    ) -> PrecommitReview:
        new_id = self._db.execute(
            "INSERT INTO precommit_reviews (project_id, file_count, findings_json) "
            "VALUES (?, ?, ?)",
            (project_id, file_count, json.dumps(findings) if findings else None),
        )
        return self.get(new_id)

    def get(self, review_id: int) -> PrecommitReview:
        row = self._db.query_one("SELECT * FROM precommit_reviews WHERE id = ?", (review_id,))
        if row is None:
            raise KeyError(f"No pre-commit review with id {review_id}")
        return self._to_review(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[PrecommitReview]:
        rows = self._db.query_all(
            "SELECT * FROM precommit_reviews WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_review(r) for r in rows]

    @staticmethod
    def _to_review(row) -> PrecommitReview:
        return PrecommitReview(
            id=row["id"],
            project_id=row["project_id"],
            file_count=row["file_count"],
            findings_json=row["findings_json"],
            created_at=row["created_at"],
        )
