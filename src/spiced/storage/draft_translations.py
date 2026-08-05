"""Draft Translation Pass persistence.

Only a trimmed excerpt of the pasted/imported dialogue and the AI's draft
translation are kept -- see ``core.draft_translation``. Always a draft for a
human translator to refine, never presented as ship-ready.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class DraftTranslation:
    id: int
    project_id: int
    source_filename: str | None
    source_format: str | None
    target_language: str | None
    entry_count: int
    raw_excerpt: str | None
    ai_draft_text: str | None
    provider: str | None
    created_at: str


class DraftTranslationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        *,
        source_filename: str | None = None,
        source_format: str | None = None,
        target_language: str | None = None,
        entry_count: int = 0,
        raw_excerpt: str | None = None,
        ai_draft_text: str | None = None,
        provider: str | None = None,
    ) -> DraftTranslation:
        new_id = self._db.execute(
            "INSERT INTO draft_translations ("
            "project_id, source_filename, source_format, target_language, entry_count, "
            "raw_excerpt, ai_draft_text, provider"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                source_filename,
                source_format,
                target_language,
                entry_count,
                raw_excerpt,
                ai_draft_text,
                provider,
            ),
        )
        return self.get(new_id)

    def get(self, translation_id: int) -> DraftTranslation:
        row = self._db.query_one(
            "SELECT * FROM draft_translations WHERE id = ?", (translation_id,)
        )
        if row is None:
            raise KeyError(f"No draft translation with id {translation_id}")
        return self._to_translation(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[DraftTranslation]:
        rows = self._db.query_all(
            "SELECT * FROM draft_translations WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_translation(r) for r in rows]

    @staticmethod
    def _to_translation(row) -> DraftTranslation:
        return DraftTranslation(
            id=row["id"],
            project_id=row["project_id"],
            source_filename=row["source_filename"],
            source_format=row["source_format"],
            target_language=row["target_language"],
            entry_count=row["entry_count"],
            raw_excerpt=row["raw_excerpt"],
            ai_draft_text=row["ai_draft_text"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
