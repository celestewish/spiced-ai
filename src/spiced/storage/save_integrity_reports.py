"""Save-integrity-report persistence, backing Save/Load Integrity Testing.

One row per run across a folder of save files: the executable and folder
used, per-save pass/fail/timeout results, and rollup counts. Only works for
games that implement Spiced's small reporting hook (see
``core.save_load_tester`` and ``docs/save_load_integrity_hook.md``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class SaveIntegrityReport:
    id: int
    project_id: int
    executable_path: str | None
    saves_folder: str | None
    results_json: str | None
    passed_count: int
    failed_count: int
    created_at: str

    @property
    def results(self) -> list:
        if not self.results_json:
            return []
        try:
            data = json.loads(self.results_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return data if isinstance(data, list) else []


class SaveIntegrityReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        executable_path: str,
        saves_folder: str,
        results: list,
        passed_count: int,
        failed_count: int,
    ) -> SaveIntegrityReport:
        new_id = self._db.execute(
            "INSERT INTO save_integrity_reports "
            "(project_id, executable_path, saves_folder, results_json, passed_count, "
            "failed_count) VALUES (?, ?, ?, ?, ?, ?)",
            (
                project_id,
                executable_path,
                saves_folder,
                json.dumps(results),
                passed_count,
                failed_count,
            ),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> SaveIntegrityReport:
        row = self._db.query_one(
            "SELECT * FROM save_integrity_reports WHERE id = ?", (report_id,)
        )
        if row is None:
            raise KeyError(f"No save integrity report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[SaveIntegrityReport]:
        rows = self._db.query_all(
            "SELECT * FROM save_integrity_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> SaveIntegrityReport:
        return SaveIntegrityReport(
            id=row["id"],
            project_id=row["project_id"],
            executable_path=row["executable_path"],
            saves_folder=row["saves_folder"],
            results_json=row["results_json"],
            passed_count=row["passed_count"],
            failed_count=row["failed_count"],
            created_at=row["created_at"],
        )
