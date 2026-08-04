"""Asset-scan-report persistence, backing the Asset Optimization Sweep.

A compact record of one read-only pass over a project's ``Assets/`` folder:
the deterministic findings (oversized/uncompressed files, orphaned assets)
and an optional AI summary. The scan itself never modifies or deletes
anything — this table only stores what was found and suggested.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class AssetScanReport:
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


class AssetScanReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        findings: dict | None = None,
        ai_summary: str | None = None,
        provider: str | None = None,
    ) -> AssetScanReport:
        new_id = self._db.execute(
            "INSERT INTO asset_scan_reports (project_id, findings_json, ai_summary, provider) "
            "VALUES (?, ?, ?, ?)",
            (project_id, json.dumps(findings) if findings else None, ai_summary, provider),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> AssetScanReport:
        row = self._db.query_one("SELECT * FROM asset_scan_reports WHERE id = ?", (report_id,))
        if row is None:
            raise KeyError(f"No asset scan report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[AssetScanReport]:
        rows = self._db.query_all(
            "SELECT * FROM asset_scan_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> AssetScanReport:
        return AssetScanReport(
            id=row["id"],
            project_id=row["project_id"],
            findings_json=row["findings_json"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
