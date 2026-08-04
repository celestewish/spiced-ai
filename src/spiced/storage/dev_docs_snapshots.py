"""Dev-docs-snapshot persistence, backing Auto-Generated Dev Docs.

Each generation (only ever triggered by an explicit "Regenerate docs" click,
never a background file-watcher — see ``core.dev_docs``) is a new row: a
running version history, not just a single "latest" cache. Scope-Creep
Flagging (``core.scope_creep``) diffs successive snapshots against each
other rather than tracking anything separately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class DevDocsSnapshot:
    id: int
    project_id: int
    source_summary_json: str | None
    ai_summary: str | None
    provider: str | None
    created_at: str

    @property
    def source_summary(self) -> dict:
        if not self.source_summary_json:
            return {}
        try:
            data = json.loads(self.source_summary_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def class_count(self) -> int:
        return int(self.source_summary.get("class_count") or 0)

    @property
    def method_count(self) -> int:
        return int(self.source_summary.get("method_count") or 0)


class DevDocsSnapshotRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        source_summary: dict | None = None,
        ai_summary: str | None = None,
        provider: str | None = None,
    ) -> DevDocsSnapshot:
        new_id = self._db.execute(
            "INSERT INTO dev_docs_snapshots (project_id, source_summary_json, ai_summary, "
            "provider) VALUES (?, ?, ?, ?)",
            (
                project_id,
                json.dumps(source_summary) if source_summary else None,
                ai_summary,
                provider,
            ),
        )
        return self.get(new_id)

    def get(self, snapshot_id: int) -> DevDocsSnapshot:
        row = self._db.query_one("SELECT * FROM dev_docs_snapshots WHERE id = ?", (snapshot_id,))
        if row is None:
            raise KeyError(f"No dev docs snapshot with id {snapshot_id}")
        return self._to_snapshot(row)

    def latest_for_project(self, project_id: int) -> DevDocsSnapshot | None:
        row = self._db.query_one(
            "SELECT * FROM dev_docs_snapshots WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (project_id,),
        )
        return self._to_snapshot(row) if row is not None else None

    def list_for_project(self, project_id: int, limit: int = 20) -> list[DevDocsSnapshot]:
        """Newest-first, matching every other repository's history() shape.

        Callers that want a chronological trend (Scope-Creep Flagging) should
        reverse this list themselves — see ``core.scope_creep``.
        """
        rows = self._db.query_all(
            "SELECT * FROM dev_docs_snapshots WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_snapshot(r) for r in rows]

    @staticmethod
    def _to_snapshot(row) -> DevDocsSnapshot:
        return DevDocsSnapshot(
            id=row["id"],
            project_id=row["project_id"],
            source_summary_json=row["source_summary_json"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
