"""Test-run persistence.

A test run is a compact record of one imported/pasted result set: a trimmed
excerpt (not the full output), the deterministic parsed summary, the AI's
written summary, and a retest checklist. Full outputs are not stored by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class TestRun:
    id: int
    project_id: int
    source_type: str
    source_filename: str | None
    raw_excerpt: str | None
    parsed_summary_json: str | None
    ai_summary: str | None
    retest_checklist_json: str | None
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
    def retest_checklist(self) -> list[str]:
        if not self.retest_checklist_json:
            return []
        try:
            data = json.loads(self.retest_checklist_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return [str(s) for s in data] if isinstance(data, list) else []


class TestRunRepository:
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
        retest_checklist: list[str] | None = None,
        provider: str | None = None,
    ) -> TestRun:
        summary_json = json.dumps(parsed_summary) if parsed_summary else None
        checklist_json = json.dumps(retest_checklist) if retest_checklist else None
        new_id = self._db.execute(
            "INSERT INTO test_runs ("
            "project_id, source_type, source_filename, raw_excerpt, parsed_summary_json, "
            "ai_summary, retest_checklist_json, provider"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                source_type,
                source_filename,
                raw_excerpt,
                summary_json,
                ai_summary,
                checklist_json,
                provider,
            ),
        )
        return self.get(new_id)

    def get(self, run_id: int) -> TestRun:
        row = self._db.query_one("SELECT * FROM test_runs WHERE id = ?", (run_id,))
        if row is None:
            raise KeyError(f"No test run with id {run_id}")
        return self._to_run(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[TestRun]:
        rows = self._db.query_all(
            "SELECT * FROM test_runs WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_run(r) for r in rows]

    @staticmethod
    def _to_run(row) -> TestRun:
        return TestRun(
            id=row["id"],
            project_id=row["project_id"],
            source_type=row["source_type"],
            source_filename=row["source_filename"],
            raw_excerpt=row["raw_excerpt"],
            parsed_summary_json=row["parsed_summary_json"],
            ai_summary=row["ai_summary"],
            retest_checklist_json=row["retest_checklist_json"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
