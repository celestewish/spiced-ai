"""Capture-run history for Visual Regression Testing (Implementation Bible,
Feature 2). One row per capture run -- just enough to find "the previous
build's screenshots" for the next run to diff against. The actual findings
from comparing two runs live in the shared ``automation_findings`` table
(Feature 0), not here.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class VisualRegressionCapture:
    id: int
    project_id: int
    screenshots_dir: str
    created_at: str


class VisualRegressionCaptureRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, project_id: int, screenshots_dir: str) -> VisualRegressionCapture:
        new_id = self._db.execute(
            "INSERT INTO visual_regression_captures (project_id, screenshots_dir) VALUES (?, ?)",
            (project_id, screenshots_dir),
        )
        return self.get(new_id)

    def get(self, capture_id: int) -> VisualRegressionCapture:
        row = self._db.query_one(
            "SELECT * FROM visual_regression_captures WHERE id = ?", (capture_id,)
        )
        if row is None:
            raise KeyError(f"No visual regression capture with id {capture_id}")
        return self._to_record(row)

    def latest_for_project(self, project_id: int) -> VisualRegressionCapture | None:
        row = self._db.query_one(
            "SELECT * FROM visual_regression_captures WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (project_id,),
        )
        return self._to_record(row) if row is not None else None

    def list_for_project(self, project_id: int, limit: int = 20) -> list[VisualRegressionCapture]:
        rows = self._db.query_all(
            "SELECT * FROM visual_regression_captures WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        return [self._to_record(r) for r in rows]

    @staticmethod
    def _to_record(row) -> VisualRegressionCapture:
        return VisualRegressionCapture(
            id=row["id"],
            project_id=row["project_id"],
            screenshots_dir=row["screenshots_dir"],
            created_at=row["created_at"],
        )
