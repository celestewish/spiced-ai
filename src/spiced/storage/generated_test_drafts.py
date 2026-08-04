"""Generated-test-draft persistence, backing Auto-Generated Unit Tests.

Every draft starts unapproved with no ``written_path``. Spiced only writes a
draft's C# text to disk the moment a developer clicks "Approve" on that
specific row (``core.test_generator.approve_and_write``) — this table's
``approved``/``written_path`` columns are the durable record that a write
happened (and where), never a queue of pending writes Spiced acts on itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class GeneratedTestDraft:
    id: int
    project_id: int
    system_label: str | None
    source_excerpt: str | None
    draft_text: str | None
    provider: str | None
    approved: bool
    written_path: str | None
    created_at: str


class GeneratedTestDraftRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        system_label: str | None,
        source_excerpt: str | None,
        draft_text: str,
        provider: str | None,
    ) -> GeneratedTestDraft:
        new_id = self._db.execute(
            "INSERT INTO generated_test_drafts "
            "(project_id, system_label, source_excerpt, draft_text, provider) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, system_label, source_excerpt, draft_text, provider),
        )
        return self.get(new_id)

    def mark_approved_and_written(self, draft_id: int, written_path: str) -> GeneratedTestDraft:
        self._db.execute(
            "UPDATE generated_test_drafts SET approved = 1, written_path = ? WHERE id = ?",
            (written_path, draft_id),
        )
        return self.get(draft_id)

    def get(self, draft_id: int) -> GeneratedTestDraft:
        row = self._db.query_one(
            "SELECT * FROM generated_test_drafts WHERE id = ?", (draft_id,)
        )
        if row is None:
            raise KeyError(f"No generated test draft with id {draft_id}")
        return self._to_draft(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[GeneratedTestDraft]:
        rows = self._db.query_all(
            "SELECT * FROM generated_test_drafts WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_draft(r) for r in rows]

    @staticmethod
    def _to_draft(row) -> GeneratedTestDraft:
        return GeneratedTestDraft(
            id=row["id"],
            project_id=row["project_id"],
            system_label=row["system_label"],
            source_excerpt=row["source_excerpt"],
            draft_text=row["draft_text"],
            provider=row["provider"],
            approved=bool(row["approved"]),
            written_path=row["written_path"],
            created_at=row["created_at"],
        )
