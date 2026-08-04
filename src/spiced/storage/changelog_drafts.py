"""Changelog-draft persistence, backing Changelog Generation.

A compact record of one patch-notes draft: the git-log/known-issues window it
was built from, the AI's draft, and the developer's edited version (if they
changed anything before copying it out). Spiced never publishes this
anywhere itself — this is scratch space for the developer's own review pass.
Distinct from the Roadmap's changelog table (Phase C), which is Spiced's own
release notes about Spiced, not the developer's game.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class ChangelogDraft:
    id: int
    project_id: int
    source_commit_range: str | None
    raw_git_log_excerpt: str | None
    ai_draft_text: str | None
    edited_text: str | None
    provider: str | None
    created_at: str

    @property
    def display_text(self) -> str:
        """The text to show/copy: the developer's edit if they saved one."""
        return self.edited_text or self.ai_draft_text or ""


class ChangelogDraftRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        source_commit_range: str | None = None,
        raw_git_log_excerpt: str | None = None,
        ai_draft_text: str | None = None,
        provider: str | None = None,
    ) -> ChangelogDraft:
        new_id = self._db.execute(
            "INSERT INTO changelog_drafts ("
            "project_id, source_commit_range, raw_git_log_excerpt, ai_draft_text, provider"
            ") VALUES (?, ?, ?, ?, ?)",
            (project_id, source_commit_range, raw_git_log_excerpt, ai_draft_text, provider),
        )
        return self.get(new_id)

    def set_edited_text(self, draft_id: int, edited_text: str) -> ChangelogDraft:
        self._db.execute(
            "UPDATE changelog_drafts SET edited_text = ? WHERE id = ?",
            (edited_text, draft_id),
        )
        return self.get(draft_id)

    def get(self, draft_id: int) -> ChangelogDraft:
        row = self._db.query_one("SELECT * FROM changelog_drafts WHERE id = ?", (draft_id,))
        if row is None:
            raise KeyError(f"No changelog draft with id {draft_id}")
        return self._to_draft(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[ChangelogDraft]:
        rows = self._db.query_all(
            "SELECT * FROM changelog_drafts WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_draft(r) for r in rows]

    @staticmethod
    def _to_draft(row) -> ChangelogDraft:
        return ChangelogDraft(
            id=row["id"],
            project_id=row["project_id"],
            source_commit_range=row["source_commit_range"],
            raw_git_log_excerpt=row["raw_git_log_excerpt"],
            ai_draft_text=row["ai_draft_text"],
            edited_text=row["edited_text"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
