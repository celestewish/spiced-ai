"""Drafted-task persistence for the Feedback-to-Task Converter.

Each row is a short, developer-editable task drafted from a feedback theme.
Spiced never syncs these anywhere — the developer accepts, edits, or copies
them to their own tracker by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database

STATUS_DRAFT = "draft"
STATUS_ACCEPTED = "accepted"
STATUS_DISMISSED = "dismissed"


@dataclass(frozen=True)
class FeedbackTask:
    id: int
    project_id: int
    batch_id: int | None
    category: str
    text: str
    status: str
    created_at: str
    updated_at: str


class FeedbackTaskRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self, project_id: int, category: str, text: str, batch_id: int | None = None
    ) -> FeedbackTask:
        new_id = self._db.execute(
            "INSERT INTO feedback_tasks (project_id, batch_id, category, text) "
            "VALUES (?, ?, ?, ?)",
            (project_id, batch_id, category, text),
        )
        return self.get(new_id)

    def update_text(self, task_id: int, text: str) -> FeedbackTask:
        self._db.execute(
            "UPDATE feedback_tasks SET text = ?, updated_at = datetime('now') WHERE id = ?",
            (text, task_id),
        )
        return self.get(task_id)

    def set_status(self, task_id: int, status: str) -> FeedbackTask:
        self._db.execute(
            "UPDATE feedback_tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, task_id),
        )
        return self.get(task_id)

    def delete(self, task_id: int) -> None:
        self._db.execute("DELETE FROM feedback_tasks WHERE id = ?", (task_id,))

    def get(self, task_id: int) -> FeedbackTask:
        row = self._db.query_one("SELECT * FROM feedback_tasks WHERE id = ?", (task_id,))
        if row is None:
            raise KeyError(f"No feedback task with id {task_id}")
        return self._to_task(row)

    def list_for_project(self, project_id: int) -> list[FeedbackTask]:
        rows = self._db.query_all(
            "SELECT * FROM feedback_tasks WHERE project_id = ? ORDER BY created_at DESC, id DESC",
            (project_id,),
        )
        return [self._to_task(r) for r in rows]

    @staticmethod
    def _to_task(row) -> FeedbackTask:
        return FeedbackTask(
            id=row["id"],
            project_id=row["project_id"],
            batch_id=row["batch_id"],
            category=row["category"],
            text=row["text"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
