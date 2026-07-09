"""Feedback-batch persistence.

A feedback batch is a compact record of one pasted/imported feedback review: a
trimmed excerpt (not the full file), the deterministic parsed summary, the local
classification, and the AI's written analysis (themes, issues, action items).
Full feedback files are not stored by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


def _loads_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


@dataclass(frozen=True)
class FeedbackBatch:
    id: int
    project_id: int
    source_type: str
    source_label: str | None
    source_filename: str | None
    entry_count: int
    raw_excerpt: str | None
    parsed_summary_json: str | None
    ai_summary: str | None
    themes_json: str | None
    issues_json: str | None
    action_items_json: str | None
    provider: str | None
    created_at: str

    @property
    def parsed_summary(self) -> dict:
        if not self.parsed_summary_json:
            return {}
        try:
            data = json.loads(self.parsed_summary_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def themes(self) -> list[str]:
        return _loads_list(self.themes_json)

    @property
    def issues(self) -> list[str]:
        return _loads_list(self.issues_json)

    @property
    def action_items(self) -> list[str]:
        return _loads_list(self.action_items_json)


class FeedbackBatchRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        source_type: str,
        entry_count: int,
        source_label: str | None = None,
        source_filename: str | None = None,
        raw_excerpt: str | None = None,
        parsed_summary: dict | None = None,
        ai_summary: str | None = None,
        themes: list[str] | None = None,
        issues: list[str] | None = None,
        action_items: list[str] | None = None,
        provider: str | None = None,
    ) -> FeedbackBatch:
        new_id = self._db.execute(
            "INSERT INTO feedback_batches ("
            "project_id, source_type, source_label, source_filename, entry_count, "
            "raw_excerpt, parsed_summary_json, ai_summary, themes_json, issues_json, "
            "action_items_json, provider"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                source_type,
                source_label,
                source_filename,
                entry_count,
                raw_excerpt,
                json.dumps(parsed_summary) if parsed_summary else None,
                ai_summary,
                json.dumps(themes) if themes else None,
                json.dumps(issues) if issues else None,
                json.dumps(action_items) if action_items else None,
                provider,
            ),
        )
        return self.get(new_id)

    def get(self, batch_id: int) -> FeedbackBatch:
        row = self._db.query_one("SELECT * FROM feedback_batches WHERE id = ?", (batch_id,))
        if row is None:
            raise KeyError(f"No feedback batch with id {batch_id}")
        return self._to_batch(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[FeedbackBatch]:
        rows = self._db.query_all(
            "SELECT * FROM feedback_batches WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_batch(r) for r in rows]

    @staticmethod
    def _to_batch(row) -> FeedbackBatch:
        return FeedbackBatch(
            id=row["id"],
            project_id=row["project_id"],
            source_type=row["source_type"],
            source_label=row["source_label"],
            source_filename=row["source_filename"],
            entry_count=row["entry_count"],
            raw_excerpt=row["raw_excerpt"],
            parsed_summary_json=row["parsed_summary_json"],
            ai_summary=row["ai_summary"],
            themes_json=row["themes_json"],
            issues_json=row["issues_json"],
            action_items_json=row["action_items_json"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
