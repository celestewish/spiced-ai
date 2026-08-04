"""Dependency-check-report persistence, backing Dependency & Plugin Update Checks.

A saved record of one pass comparing a project's ``Packages/manifest.json``
against the public Unity Package Registry, plus an optional AI summary. The
check itself is read-only — this table only stores what was found.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class DependencyCheckReport:
    id: int
    project_id: int
    findings_json: str | None
    ai_summary: str | None
    provider: str | None
    created_at: str

    @property
    def findings(self) -> dict:
        if not self.findings_json:
            return {}
        try:
            data = json.loads(self.findings_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}


class DependencyCheckReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        findings: dict | None = None,
        ai_summary: str | None = None,
        provider: str | None = None,
    ) -> DependencyCheckReport:
        new_id = self._db.execute(
            "INSERT INTO dependency_check_reports (project_id, findings_json, ai_summary, "
            "provider) VALUES (?, ?, ?, ?)",
            (project_id, json.dumps(findings) if findings else None, ai_summary, provider),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> DependencyCheckReport:
        row = self._db.query_one(
            "SELECT * FROM dependency_check_reports WHERE id = ?", (report_id,)
        )
        if row is None:
            raise KeyError(f"No dependency check report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[DependencyCheckReport]:
        rows = self._db.query_all(
            "SELECT * FROM dependency_check_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> DependencyCheckReport:
        return DependencyCheckReport(
            id=row["id"],
            project_id=row["project_id"],
            findings_json=row["findings_json"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
