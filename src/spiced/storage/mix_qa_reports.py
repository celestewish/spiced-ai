"""Mix/Level QA persistence.

Each row is one saved local WAV batch analysis (``core.mix_level_qa``) --
purely deterministic (``wave``/``struct``/``array``, no AI call), so only the
structured findings need to be kept. Same minimal shape as
``localization_readiness_reports``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class MixQaReport:
    id: int
    project_id: int
    findings_json: str | None
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


class MixQaReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project_id: int, findings: dict) -> MixQaReport:
        new_id = self._db.execute(
            "INSERT INTO mix_qa_reports (project_id, findings_json) VALUES (?, ?)",
            (project_id, json.dumps(findings)),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> MixQaReport:
        row = self._db.query_one("SELECT * FROM mix_qa_reports WHERE id = ?", (report_id,))
        if row is None:
            raise KeyError(f"No mix QA report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[MixQaReport]:
        rows = self._db.query_all(
            "SELECT * FROM mix_qa_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> MixQaReport:
        return MixQaReport(
            id=row["id"],
            project_id=row["project_id"],
            findings_json=row["findings_json"],
            created_at=row["created_at"],
        )
