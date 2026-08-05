"""Contract/License Checklist persistence.

Deliberately stores far less than the developer pastes in: a short preview
excerpt (not the full contract text), a hash reference to what was actually
reviewed, and the AI's output. See ``core.contract_checklist`` for the exact
capping discipline -- a contract/license document is more sensitive than a
debug log or feedback batch, so this mirrors (and tightens) the excerpt-
capping approach those tables already use.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class ContractChecklistReview:
    id: int
    project_id: int
    source_filename: str | None
    excerpt_hash: str | None
    excerpt_preview: str | None
    ai_summary: str | None
    provider: str | None
    created_at: str


class ContractChecklistReviewRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        *,
        source_filename: str | None = None,
        excerpt_hash: str | None = None,
        excerpt_preview: str | None = None,
        ai_summary: str | None = None,
        provider: str | None = None,
    ) -> ContractChecklistReview:
        new_id = self._db.execute(
            "INSERT INTO contract_checklist_reviews ("
            "project_id, source_filename, excerpt_hash, excerpt_preview, ai_summary, provider"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, source_filename, excerpt_hash, excerpt_preview, ai_summary, provider),
        )
        return self.get(new_id)

    def get(self, review_id: int) -> ContractChecklistReview:
        row = self._db.query_one(
            "SELECT * FROM contract_checklist_reviews WHERE id = ?", (review_id,)
        )
        if row is None:
            raise KeyError(f"No contract checklist review with id {review_id}")
        return self._to_review(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[ContractChecklistReview]:
        rows = self._db.query_all(
            "SELECT * FROM contract_checklist_reviews WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_review(r) for r in rows]

    @staticmethod
    def _to_review(row) -> ContractChecklistReview:
        return ContractChecklistReview(
            id=row["id"],
            project_id=row["project_id"],
            source_filename=row["source_filename"],
            excerpt_hash=row["excerpt_hash"],
            excerpt_preview=row["excerpt_preview"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
