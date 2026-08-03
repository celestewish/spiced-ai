"""Session-summary persistence, backing the Session Summaries feature.

A session summary is a compact devlog-style recap of what was tested, fixed,
and still open since the previous summary (or app start). Always saved
locally; ``synced_to_team`` only tracks whether it was also posted to the
team backend — see core/session_summary.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class SessionSummary:
    id: int
    project_id: int
    started_at: str
    ended_at: str
    tested_summary: str | None
    fixed_summary: str | None
    open_summary: str | None
    ai_summary: str | None
    synced_to_team: bool
    created_at: str


class SessionSummaryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        started_at: str,
        ended_at: str,
        tested_summary: str | None = None,
        fixed_summary: str | None = None,
        open_summary: str | None = None,
        ai_summary: str | None = None,
    ) -> SessionSummary:
        new_id = self._db.execute(
            "INSERT INTO session_summaries ("
            "project_id, started_at, ended_at, tested_summary, fixed_summary, open_summary, "
            "ai_summary"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                started_at,
                ended_at,
                tested_summary,
                fixed_summary,
                open_summary,
                ai_summary,
            ),
        )
        return self.get(new_id)

    def mark_synced(self, summary_id: int) -> SessionSummary:
        self._db.execute(
            "UPDATE session_summaries SET synced_to_team = 1 WHERE id = ?", (summary_id,)
        )
        return self.get(summary_id)

    def get(self, summary_id: int) -> SessionSummary:
        row = self._db.query_one("SELECT * FROM session_summaries WHERE id = ?", (summary_id,))
        if row is None:
            raise KeyError(f"No session summary with id {summary_id}")
        return self._to_summary(row)

    def latest_for_project(self, project_id: int) -> SessionSummary | None:
        row = self._db.query_one(
            "SELECT * FROM session_summaries WHERE project_id = ? "
            "ORDER BY ended_at DESC, id DESC LIMIT 1",
            (project_id,),
        )
        return self._to_summary(row) if row is not None else None

    def list_for_project(self, project_id: int, limit: int = 20) -> list[SessionSummary]:
        rows = self._db.query_all(
            "SELECT * FROM session_summaries WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_summary(r) for r in rows]

    @staticmethod
    def _to_summary(row) -> SessionSummary:
        return SessionSummary(
            id=row["id"],
            project_id=row["project_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            tested_summary=row["tested_summary"],
            fixed_summary=row["fixed_summary"],
            open_summary=row["open_summary"],
            ai_summary=row["ai_summary"],
            synced_to_team=bool(row["synced_to_team"]),
            created_at=row["created_at"],
        )
