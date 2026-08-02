"""Performance-report persistence.

A compact record of one imported/pasted performance pass: a trimmed excerpt,
the deterministic parsed summary (fps/memory/load-time spikes), the AI's
written interpretation, and the target-hardware tier if a simulation was run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class PerformanceReport:
    id: int
    project_id: int
    source_type: str
    source_filename: str | None
    target_hardware: str | None
    raw_excerpt: str | None
    parsed_summary_json: str | None
    ai_summary: str | None
    spikes_json: str | None
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
    def spikes(self) -> list[dict]:
        if not self.spikes_json:
            return []
        try:
            data = json.loads(self.spikes_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return data if isinstance(data, list) else []


class PerformanceReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        source_type: str,
        source_filename: str | None = None,
        target_hardware: str | None = None,
        raw_excerpt: str | None = None,
        parsed_summary: dict | None = None,
        ai_summary: str | None = None,
        spikes: list[dict] | None = None,
        provider: str | None = None,
    ) -> PerformanceReport:
        new_id = self._db.execute(
            "INSERT INTO performance_reports ("
            "project_id, source_type, source_filename, target_hardware, raw_excerpt, "
            "parsed_summary_json, ai_summary, spikes_json, provider"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                source_type,
                source_filename,
                target_hardware,
                raw_excerpt,
                json.dumps(parsed_summary) if parsed_summary else None,
                ai_summary,
                json.dumps(spikes) if spikes else None,
                provider,
            ),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> PerformanceReport:
        row = self._db.query_one("SELECT * FROM performance_reports WHERE id = ?", (report_id,))
        if row is None:
            raise KeyError(f"No performance report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[PerformanceReport]:
        rows = self._db.query_all(
            "SELECT * FROM performance_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> PerformanceReport:
        return PerformanceReport(
            id=row["id"],
            project_id=row["project_id"],
            source_type=row["source_type"],
            source_filename=row["source_filename"],
            target_hardware=row["target_hardware"],
            raw_excerpt=row["raw_excerpt"],
            parsed_summary_json=row["parsed_summary_json"],
            ai_summary=row["ai_summary"],
            spikes_json=row["spikes_json"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
