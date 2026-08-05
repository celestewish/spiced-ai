"""Trailer & Screenshot Checklist persistence (screenshots only — see
core.trailer_screenshot_checklist for why video trailer analysis is out of
scope).

``findings_json`` holds Spiced's own deterministic per-image findings
(resolution/aspect ratio, blank-shot heuristic); ``ai_summary`` is the AI's
review of those structured findings plus any developer-supplied captions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class ScreenshotChecklistReport:
    id: int
    project_id: int
    findings_json: str | None
    ai_summary: str | None
    provider: str | None
    created_at: str

    @property
    def findings(self) -> list[dict]:
        if not self.findings_json:
            return []
        try:
            data = json.loads(self.findings_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return data if isinstance(data, list) else []


class ScreenshotChecklistReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        findings_json: str | None,
        ai_summary: str | None,
        provider: str | None,
    ) -> ScreenshotChecklistReport:
        new_id = self._db.execute(
            "INSERT INTO screenshot_checklist_reports "
            "(project_id, findings_json, ai_summary, provider) VALUES (?, ?, ?, ?)",
            (project_id, findings_json, ai_summary, provider),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> ScreenshotChecklistReport:
        row = self._db.query_one(
            "SELECT * FROM screenshot_checklist_reports WHERE id = ?", (report_id,)
        )
        if row is None:
            raise KeyError(f"No screenshot checklist report with id {report_id}")
        return self._to_report(row)

    def list_for_project(
        self, project_id: int, limit: int = 20
    ) -> list[ScreenshotChecklistReport]:
        rows = self._db.query_all(
            "SELECT * FROM screenshot_checklist_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> ScreenshotChecklistReport:
        return ScreenshotChecklistReport(
            id=row["id"],
            project_id=row["project_id"],
            findings_json=row["findings_json"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
