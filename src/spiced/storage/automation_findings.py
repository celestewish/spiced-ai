"""Persistence for the shared automation Finding schema (Implementation
Bible, Feature 0). One row per run, across every Bible automation feature --
``feature_id`` namespaces rows (e.g. ``'audio.loudness_normalize'``,
``'vfx.visual_regression'``) rather than each feature getting its own table,
so the Testing/Debugging results UI and regression-tracking history can
query across all of them the same way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.automation.finding import Finding
from spiced.storage.database import Database


@dataclass(frozen=True)
class AutomationFindingRecord:
    id: int
    run_id: str
    feature_id: str
    project_id: int
    status: str
    summary: str
    items_json: str
    created_at: str

    @property
    def items(self) -> list[dict]:
        try:
            data = json.loads(self.items_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return data if isinstance(data, list) else []


class AutomationFindingRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project_id: int, finding: Finding) -> AutomationFindingRecord:
        new_id = self._db.execute(
            "INSERT INTO automation_findings "
            "(run_id, feature_id, project_id, status, summary, items_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                finding.run_id,
                finding.feature_id,
                project_id,
                finding.status,
                finding.summary,
                json.dumps([item.as_dict() for item in finding.items]),
            ),
        )
        return self.get(new_id)

    def get(self, record_id: int) -> AutomationFindingRecord:
        row = self._db.query_one("SELECT * FROM automation_findings WHERE id = ?", (record_id,))
        if row is None:
            raise KeyError(f"No automation finding with id {record_id}")
        return self._to_record(row)

    def get_by_run_id(self, run_id: str) -> AutomationFindingRecord | None:
        row = self._db.query_one(
            "SELECT * FROM automation_findings WHERE run_id = ?", (run_id,)
        )
        return self._to_record(row) if row is not None else None

    def list_for_project(
        self, project_id: int, *, feature_id: str | None = None, limit: int = 20
    ) -> list[AutomationFindingRecord]:
        if feature_id is not None:
            rows = self._db.query_all(
                "SELECT * FROM automation_findings WHERE project_id = ? AND feature_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (project_id, feature_id, limit),
            )
        else:
            rows = self._db.query_all(
                "SELECT * FROM automation_findings WHERE project_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (project_id, limit),
            )
        return [self._to_record(r) for r in rows]

    @staticmethod
    def _to_record(row) -> AutomationFindingRecord:
        return AutomationFindingRecord(
            id=row["id"],
            run_id=row["run_id"],
            feature_id=row["feature_id"],
            project_id=row["project_id"],
            status=row["status"],
            summary=row["summary"],
            items_json=row["items_json"],
            created_at=row["created_at"],
        )
