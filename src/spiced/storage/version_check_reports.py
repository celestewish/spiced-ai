"""Version-check report persistence.

A compact record of one deprecated-API scan: the trimmed excerpt, the
deterministic hit list, and the AI's narrative summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class VersionCheckReport:
    id: int
    project_id: int
    source_filename: str | None
    raw_excerpt: str | None
    hits_json: str | None
    ai_summary: str | None
    provider: str | None
    created_at: str

    @property
    def hits(self) -> list[dict]:
        if not self.hits_json:
            return []
        try:
            data = json.loads(self.hits_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return data if isinstance(data, list) else []


class VersionCheckReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        source_filename: str | None = None,
        raw_excerpt: str | None = None,
        hits: list[dict] | None = None,
        ai_summary: str | None = None,
        provider: str | None = None,
    ) -> VersionCheckReport:
        new_id = self._db.execute(
            "INSERT INTO version_check_reports ("
            "project_id, source_filename, raw_excerpt, hits_json, ai_summary, provider"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                project_id,
                source_filename,
                raw_excerpt,
                json.dumps(hits) if hits else None,
                ai_summary,
                provider,
            ),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> VersionCheckReport:
        row = self._db.query_one("SELECT * FROM version_check_reports WHERE id = ?", (report_id,))
        if row is None:
            raise KeyError(f"No version check report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[VersionCheckReport]:
        rows = self._db.query_all(
            "SELECT * FROM version_check_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> VersionCheckReport:
        return VersionCheckReport(
            id=row["id"],
            project_id=row["project_id"],
            source_filename=row["source_filename"],
            raw_excerpt=row["raw_excerpt"],
            hits_json=row["hits_json"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
