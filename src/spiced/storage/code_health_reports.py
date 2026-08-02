"""Code-health report persistence.

A compact record of one code-health pass over a pasted/imported script: the
deterministic metrics, a trimmed excerpt, and the AI's non-judgmental summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class CodeHealthReport:
    id: int
    project_id: int
    source_filename: str | None
    raw_excerpt: str | None
    metrics_json: str | None
    ai_summary: str | None
    provider: str | None
    created_at: str

    @property
    def metrics(self) -> dict:
        if not self.metrics_json:
            return {}
        try:
            data = json.loads(self.metrics_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}


class CodeHealthReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        source_filename: str | None = None,
        raw_excerpt: str | None = None,
        metrics: dict | None = None,
        ai_summary: str | None = None,
        provider: str | None = None,
    ) -> CodeHealthReport:
        new_id = self._db.execute(
            "INSERT INTO code_health_reports ("
            "project_id, source_filename, raw_excerpt, metrics_json, ai_summary, provider"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                project_id,
                source_filename,
                raw_excerpt,
                json.dumps(metrics) if metrics else None,
                ai_summary,
                provider,
            ),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> CodeHealthReport:
        row = self._db.query_one("SELECT * FROM code_health_reports WHERE id = ?", (report_id,))
        if row is None:
            raise KeyError(f"No code health report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[CodeHealthReport]:
        rows = self._db.query_all(
            "SELECT * FROM code_health_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> CodeHealthReport:
        return CodeHealthReport(
            id=row["id"],
            project_id=row["project_id"],
            source_filename=row["source_filename"],
            raw_excerpt=row["raw_excerpt"],
            metrics_json=row["metrics_json"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
