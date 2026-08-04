"""Economy-simulation-report persistence, backing Economy/Balance Simulation.

A saved record of one deterministic simulation run over developer-supplied
economy data (see ``core.economy_simulator`` for the documented input
schema): the raw input (so a report is reproducible/inspectable later), the
computed findings, and an optional AI plain-language summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class EconomySimulationReport:
    id: int
    project_id: int
    input_json: str | None
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


class EconomySimulationReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        input_data: dict | None,
        findings: dict | None,
        ai_summary: str | None = None,
        provider: str | None = None,
    ) -> EconomySimulationReport:
        new_id = self._db.execute(
            "INSERT INTO economy_simulation_reports "
            "(project_id, input_json, findings_json, ai_summary, provider) VALUES (?, ?, ?, ?, ?)",
            (
                project_id,
                json.dumps(input_data) if input_data else None,
                json.dumps(findings) if findings else None,
                ai_summary,
                provider,
            ),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> EconomySimulationReport:
        row = self._db.query_one(
            "SELECT * FROM economy_simulation_reports WHERE id = ?", (report_id,)
        )
        if row is None:
            raise KeyError(f"No economy simulation report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[EconomySimulationReport]:
        rows = self._db.query_all(
            "SELECT * FROM economy_simulation_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> EconomySimulationReport:
        return EconomySimulationReport(
            id=row["id"],
            project_id=row["project_id"],
            input_json=row["input_json"],
            findings_json=row["findings_json"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
