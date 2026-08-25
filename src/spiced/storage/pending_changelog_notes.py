"""Persistence for queued changelog notes (Market-Viability Roadmap, Phase
4's ``queue_changelog_note`` rules-engine action).

Purely local scratch space -- see ``core.changelog_draft``'s module
docstring on why Changelog Generation itself never leaves the developer's
machine. A queued note is never auto-published; it's incorporated as extra
context the next time ``ChangelogService.draft`` runs, then marked
consumed (see ``mark_consumed``), never deleted.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class PendingChangelogNote:
    id: int
    project_id: int
    note_text: str
    source_event_kind: str | None
    created_at: str
    consumed_at: str | None


class PendingChangelogNoteRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def queue(
        self, project_id: int, note_text: str, source_event_kind: str | None = None
    ) -> PendingChangelogNote:
        new_id = self._db.execute(
            "INSERT INTO pending_changelog_notes (project_id, note_text, source_event_kind) "
            "VALUES (?, ?, ?)",
            (project_id, note_text, source_event_kind),
        )
        return self.get(new_id)

    def get(self, note_id: int) -> PendingChangelogNote:
        row = self._db.query_one(
            "SELECT * FROM pending_changelog_notes WHERE id = ?", (note_id,)
        )
        if row is None:
            raise KeyError(f"No pending changelog note with id {note_id}")
        return self._to_note(row)

    def list_pending(self, project_id: int) -> list[PendingChangelogNote]:
        """Unconsumed notes for a project, oldest first -- the order a
        developer would expect their queued items narrated in a draft."""
        rows = self._db.query_all(
            "SELECT * FROM pending_changelog_notes WHERE project_id = ? AND consumed_at IS NULL "
            "ORDER BY created_at ASC, id ASC",
            (project_id,),
        )
        return [self._to_note(r) for r in rows]

    def mark_consumed(self, note_ids: list[int]) -> None:
        if not note_ids:
            return
        placeholders = ", ".join("?" for _ in note_ids)
        self._db.execute(
            f"UPDATE pending_changelog_notes SET consumed_at = datetime('now') "
            f"WHERE id IN ({placeholders})",
            note_ids,
        )

    @staticmethod
    def _to_note(row) -> PendingChangelogNote:
        return PendingChangelogNote(
            id=row["id"],
            project_id=row["project_id"],
            note_text=row["note_text"],
            source_event_kind=row["source_event_kind"],
            created_at=row["created_at"],
            consumed_at=row["consumed_at"],
        )
