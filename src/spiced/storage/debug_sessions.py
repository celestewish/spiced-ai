"""Debug session persistence.

Stores a compact record of each analysis: the detected error, a relevant
excerpt (not the full log), a short summary, and suggested next steps. Full
imported logs are intentionally NOT stored by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class DebugSession:
    id: int
    project_id: int
    source_type: str
    source_filename: str | None
    detected_error_type: str | None
    detected_file: str | None
    detected_line: int | None
    raw_excerpt: str | None
    summary: str | None
    suggested_next_steps_json: str | None
    provider: str | None
    created_at: str

    @property
    def suggested_next_steps(self) -> list[str]:
        if not self.suggested_next_steps_json:
            return []
        try:
            data = json.loads(self.suggested_next_steps_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return [str(s) for s in data] if isinstance(data, list) else []


class DebugSessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        source_type: str,
        summary: str | None,
        detected_error_type: str | None = None,
        detected_file: str | None = None,
        detected_line: int | None = None,
        raw_excerpt: str | None = None,
        source_filename: str | None = None,
        suggested_next_steps: list[str] | None = None,
        provider: str | None = None,
    ) -> DebugSession:
        steps_json = json.dumps(suggested_next_steps) if suggested_next_steps else None
        new_id = self._db.execute(
            "INSERT INTO debug_sessions ("
            "project_id, source_type, source_filename, detected_error_type, detected_file, "
            "detected_line, raw_excerpt, summary, suggested_next_steps_json, provider"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                source_type,
                source_filename,
                detected_error_type,
                detected_file,
                detected_line,
                raw_excerpt,
                summary,
                steps_json,
                provider,
            ),
        )
        return self.get(new_id)

    def get(self, session_id: int) -> DebugSession:
        row = self._db.query_one("SELECT * FROM debug_sessions WHERE id = ?", (session_id,))
        if row is None:
            raise KeyError(f"No debug session with id {session_id}")
        return self._to_session(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[DebugSession]:
        rows = self._db.query_all(
            "SELECT * FROM debug_sessions WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_session(r) for r in rows]

    @staticmethod
    def _to_session(row) -> DebugSession:
        return DebugSession(
            id=row["id"],
            project_id=row["project_id"],
            source_type=row["source_type"],
            source_filename=row["source_filename"],
            detected_error_type=row["detected_error_type"],
            detected_file=row["detected_file"],
            detected_line=row["detected_line"],
            raw_excerpt=row["raw_excerpt"],
            summary=row["summary"],
            suggested_next_steps_json=row["suggested_next_steps_json"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
