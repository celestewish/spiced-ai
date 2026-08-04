"""Design-doc-upload persistence, backing Design Doc Sync.

A dev's own game design doc (never the Spiced product spec), pasted or
imported per project. Opt-in per project — see
``projects.design_doc_sync_enabled`` — and purely local; the text only ever
leaves this machine as part of an explicit "Check design drift" AI call the
developer triggers themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class DesignDocUpload:
    id: int
    project_id: int
    filename: str | None
    text: str
    uploaded_at: str


class DesignDocUploadRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project_id: int, text: str, filename: str | None = None) -> DesignDocUpload:
        new_id = self._db.execute(
            "INSERT INTO design_doc_uploads (project_id, filename, text) VALUES (?, ?, ?)",
            (project_id, filename, text),
        )
        return self.get(new_id)

    def get(self, upload_id: int) -> DesignDocUpload:
        row = self._db.query_one("SELECT * FROM design_doc_uploads WHERE id = ?", (upload_id,))
        if row is None:
            raise KeyError(f"No design doc upload with id {upload_id}")
        return self._to_upload(row)

    def latest_for_project(self, project_id: int) -> DesignDocUpload | None:
        row = self._db.query_one(
            "SELECT * FROM design_doc_uploads WHERE project_id = ? "
            "ORDER BY uploaded_at DESC, id DESC LIMIT 1",
            (project_id,),
        )
        return self._to_upload(row) if row is not None else None

    def list_for_project(self, project_id: int, limit: int = 20) -> list[DesignDocUpload]:
        rows = self._db.query_all(
            "SELECT * FROM design_doc_uploads WHERE project_id = ? "
            "ORDER BY uploaded_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_upload(r) for r in rows]

    @staticmethod
    def _to_upload(row) -> DesignDocUpload:
        return DesignDocUpload(
            id=row["id"],
            project_id=row["project_id"],
            filename=row["filename"],
            text=row["text"],
            uploaded_at=row["uploaded_at"],
        )
