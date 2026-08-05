"""Idempotency log for ingesting player-submitted crash reports.

Each remote crash-report id (minted by the backend) is recorded here exactly
once so re-syncing (e.g. the developer clicking "Sync player crash reports"
again) never re-feeds the same report into Known Issues and inflates
``known_issues.occurrences``. See core.player_crash_reports.
"""

from __future__ import annotations

from spiced.storage.database import Database


class PlayerCrashSyncRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def is_ingested(self, project_id: int, remote_report_id: str) -> bool:
        row = self._db.query_one(
            "SELECT id FROM player_crash_sync_log WHERE project_id = ? AND remote_report_id = ?",
            (project_id, remote_report_id),
        )
        return row is not None

    def mark_ingested(self, project_id: int, remote_report_id: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO player_crash_sync_log (project_id, remote_report_id) "
            "VALUES (?, ?)",
            (project_id, remote_report_id),
        )
