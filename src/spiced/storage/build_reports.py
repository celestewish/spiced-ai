"""Build-report persistence, backing the Automated Build Pipeline.

A compact record of one headless Unity build Spiced triggered — manually,
from the in-app scheduler, or (once Phase E's pre-commit hook exists) from a
commit. Mirrors the always-read-the-results-regardless-of-exit-code
philosophy of ``unity_test_runner``/test runs: ``succeeded`` and ``log_tail``
are recorded whatever happened, so a failed build still leaves a trail.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database

TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULED = "scheduled"
TRIGGER_COMMIT = "commit"


@dataclass(frozen=True)
class BuildReport:
    id: int
    project_id: int
    trigger: str
    target_platform: str | None
    started_at: str
    finished_at: str | None
    succeeded: bool | None
    log_tail: str | None
    output_path: str | None
    marked_stable: bool
    created_at: str


class BuildReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        trigger: str,
        started_at: str,
        finished_at: str | None = None,
        target_platform: str | None = None,
        succeeded: bool | None = None,
        log_tail: str | None = None,
        output_path: str | None = None,
    ) -> BuildReport:
        new_id = self._db.execute(
            "INSERT INTO build_reports ("
            "project_id, trigger, target_platform, started_at, finished_at, succeeded, "
            "log_tail, output_path"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                trigger,
                target_platform,
                started_at,
                finished_at,
                None if succeeded is None else (1 if succeeded else 0),
                log_tail,
                output_path,
            ),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> BuildReport:
        row = self._db.query_one("SELECT * FROM build_reports WHERE id = ?", (report_id,))
        if row is None:
            raise KeyError(f"No build report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[BuildReport]:
        rows = self._db.query_all(
            "SELECT * FROM build_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    def latest_for_project(self, project_id: int) -> BuildReport | None:
        rows = self.list_for_project(project_id, limit=1)
        return rows[0] if rows else None

    def latest_stable_for_project(self, project_id: int) -> BuildReport | None:
        row = self._db.query_one(
            "SELECT * FROM build_reports WHERE project_id = ? AND marked_stable = 1 "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (project_id,),
        )
        return self._to_report(row) if row is not None else None

    def mark_stable(self, report_id: int) -> BuildReport:
        """Mark one build stable. Only one build is "the" stable build at a
        time: clearing any previous flag for the same project keeps
        ``latest_stable_for_project`` a single, unambiguous answer."""
        report = self.get(report_id)
        self._db.execute(
            "UPDATE build_reports SET marked_stable = 0 WHERE project_id = ?",
            (report.project_id,),
        )
        self._db.execute(
            "UPDATE build_reports SET marked_stable = 1 WHERE id = ?", (report_id,)
        )
        return self.get(report_id)

    @staticmethod
    def _to_report(row) -> BuildReport:
        return BuildReport(
            id=row["id"],
            project_id=row["project_id"],
            trigger=row["trigger"],
            target_platform=row["target_platform"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            succeeded=None if row["succeeded"] is None else bool(row["succeeded"]),
            log_tail=row["log_tail"],
            output_path=row["output_path"],
            marked_stable=bool(row["marked_stable"]),
            created_at=row["created_at"],
        )
