"""Design-doc-sync-report persistence, backing Design Doc Sync.

One row per AI comparison between a project's latest uploaded design-doc
text and its latest Dev Docs snapshot — flags meaningful drift either
direction, framed as "reconcile the doc or rein in scope," never a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class DesignDocSyncReport:
    id: int
    project_id: int
    design_doc_upload_id: int
    dev_docs_snapshot_id: int
    ai_summary: str | None
    provider: str | None
    created_at: str


class DesignDocSyncReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        design_doc_upload_id: int,
        dev_docs_snapshot_id: int,
        ai_summary: str | None = None,
        provider: str | None = None,
    ) -> DesignDocSyncReport:
        new_id = self._db.execute(
            "INSERT INTO design_doc_sync_reports (project_id, design_doc_upload_id, "
            "dev_docs_snapshot_id, ai_summary, provider) VALUES (?, ?, ?, ?, ?)",
            (project_id, design_doc_upload_id, dev_docs_snapshot_id, ai_summary, provider),
        )
        return self.get(new_id)

    def get(self, report_id: int) -> DesignDocSyncReport:
        row = self._db.query_one(
            "SELECT * FROM design_doc_sync_reports WHERE id = ?", (report_id,)
        )
        if row is None:
            raise KeyError(f"No design doc sync report with id {report_id}")
        return self._to_report(row)

    def list_for_project(self, project_id: int, limit: int = 20) -> list[DesignDocSyncReport]:
        rows = self._db.query_all(
            "SELECT * FROM design_doc_sync_reports WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_report(r) for r in rows]

    @staticmethod
    def _to_report(row) -> DesignDocSyncReport:
        return DesignDocSyncReport(
            id=row["id"],
            project_id=row["project_id"],
            design_doc_upload_id=row["design_doc_upload_id"],
            dev_docs_snapshot_id=row["dev_docs_snapshot_id"],
            ai_summary=row["ai_summary"],
            provider=row["provider"],
            created_at=row["created_at"],
        )
