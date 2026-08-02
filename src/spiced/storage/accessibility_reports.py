"""Accessibility-report persistence.

A compact record of one accessibility pass: the deterministic checklist score
and findings, a trimmed excerpt, and the AI's plain-language write-up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class AccessibilityReport:
    id: int
    project_id: int
    source_type: str
    source_filename: str | None
    raw_excerpt: str | None
    parsed_summary_json: str | None
    ai_summary: str | None
    findings_json: str | None
    score: int | None
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
    def findings(self) -> list[dict]:
        if not self.findings_json:
            return []
        try:
            data = json.loads(self.findings_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return data if isinstance(data, list) else []


class AccessibilityReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        source_type: str,
        source_filename: str | None = None,
        raw_excerpt: str | None = None,
        parsed_summary: dict | None = None,
        ai_summary: str | None = None,
        findings: list[dict] | None = None,
        score: int | None = None,
        provider: str | None = None,
    ) -> AccessibilityReport:
        new_id = self._db.execute(
            "INSERT INTO accessibility_reports ("
            "project_id, source_type, source_filename, raw_excerpt, parsed_summary_json, "
            "ai_summary, findings_json, score, provider"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                source_type,
                source_filename,
                raw_excerpt,
                json.dumps(parsed_summary) if parsed_summary else None,
                ai_summary,
                json.dumps(findings) if findings else None,
                score,
                provider,
            ),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> AccessibilityReport:
        row = self._db.query_one("SELECT * FROM accessibility_reports WHERE id = ?", (report_id,))
        if row is None:
            raise KeyError(f"No accessibility report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[AccessibilityReport]:
        rows = self._db.query_all(
            "SELECT * FROM accessibility_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> AccessibilityReport:
        return AccessibilityReport(
            id=row["id"],
            project_id=row["project_id"],
            source_type=row["source_type"],
            source_filename=row["source_filename"],
            raw_excerpt=row["raw_excerpt"],
            parsed_summary_json=row["parsed_summary_json"],
            ai_summary=row["ai_summary"],
            findings_json=row["findings_json"],
            score=row["score"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
