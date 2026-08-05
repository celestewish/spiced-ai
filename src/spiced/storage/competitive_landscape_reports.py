"""Competitive Landscape Scan persistence.

Only a trimmed excerpt of the developer's own game description and the AI's
approximate, not-live-data positioning read are kept -- see
``core.competitive_landscape``.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class CompetitiveLandscapeReport:
    id: int
    project_id: int
    description_excerpt: str | None
    ai_summary: str | None
    provider: str | None
    created_at: str


class CompetitiveLandscapeReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        *,
        description_excerpt: str | None = None,
        ai_summary: str | None = None,
        provider: str | None = None,
    ) -> CompetitiveLandscapeReport:
        new_id = self._db.execute(
            "INSERT INTO competitive_landscape_reports ("
            "project_id, description_excerpt, ai_summary, provider"
            ") VALUES (?, ?, ?, ?)",
            (project_id, description_excerpt, ai_summary, provider),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> CompetitiveLandscapeReport:
        row = self._db.query_one(
            "SELECT * FROM competitive_landscape_reports WHERE id = ?", (report_id,)
        )
        if row is None:
            raise KeyError(f"No competitive landscape report with id {report_id}")
        return self._to_report(row)

    def list_for_project(
        self, project_id: int, limit: int = 20
    ) -> list[CompetitiveLandscapeReport]:
        rows = self._db.query_all(
            "SELECT * FROM competitive_landscape_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> CompetitiveLandscapeReport:
        return CompetitiveLandscapeReport(
            id=row["id"],
            project_id=row["project_id"],
            description_excerpt=row["description_excerpt"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
