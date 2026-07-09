"""Manual test-case persistence.

A test case is a small, developer-authored checklist item scoped to a project:
what to verify, how, what's expected, and its current pass/fail status. Spiced
never runs these — the developer records results by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database

CATEGORIES = (
    "Gameplay",
    "UI",
    "Controls",
    "Progression",
    "Save/Load",
    "Performance",
    "Build Readiness",
    "Accessibility",
    "General",
)
DEFAULT_CATEGORY = "General"

PRIORITIES = ("Low", "Medium", "High", "Critical")
DEFAULT_PRIORITY = "Medium"

STATUSES = ("Not Run", "Pass", "Fail", "Blocked")
DEFAULT_STATUS = "Not Run"


@dataclass(frozen=True)
class TestCase:
    id: int
    project_id: int
    title: str
    category: str
    priority: str
    steps: str | None
    expected_result: str | None
    status: str
    failure_note: str | None
    created_at: str
    updated_at: str


class TestCaseRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        project_id: int,
        title: str,
        category: str = DEFAULT_CATEGORY,
        priority: str = DEFAULT_PRIORITY,
        steps: str | None = None,
        expected_result: str | None = None,
        status: str = DEFAULT_STATUS,
    ) -> TestCase:
        title = title.strip()
        if not title:
            raise ValueError("Test case title cannot be empty.")
        category = category if category in CATEGORIES else DEFAULT_CATEGORY
        priority = priority if priority in PRIORITIES else DEFAULT_PRIORITY
        status = status if status in STATUSES else DEFAULT_STATUS
        new_id = self._db.execute(
            "INSERT INTO test_cases ("
            "project_id, title, category, priority, steps, expected_result, status"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, title, category, priority, steps, expected_result, status),
        )
        return self.get(new_id)

    def set_status(
        self, test_case_id: int, status: str, failure_note: str | None = None
    ) -> TestCase:
        if status not in STATUSES:
            raise ValueError(f"Unknown status: {status}")
        # A note only makes sense for a failure; clear it otherwise to avoid stale text.
        note = failure_note if status == "Fail" else None
        self._db.execute(
            "UPDATE test_cases SET status = ?, failure_note = ?, updated_at = datetime('now') "
            "WHERE id = ?",
            (status, note, test_case_id),
        )
        return self.get(test_case_id)

    def get(self, test_case_id: int) -> TestCase:
        row = self._db.query_one("SELECT * FROM test_cases WHERE id = ?", (test_case_id,))
        if row is None:
            raise KeyError(f"No test case with id {test_case_id}")
        return self._to_case(row)

    def list_for_project(self, project_id: int) -> list[TestCase]:
        rows = self._db.query_all(
            "SELECT * FROM test_cases WHERE project_id = ? ORDER BY created_at ASC, id ASC",
            (project_id,),
        )
        return [self._to_case(r) for r in rows]

    @staticmethod
    def _to_case(row) -> TestCase:
        return TestCase(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            category=row["category"],
            priority=row["priority"],
            steps=row["steps"],
            expected_result=row["expected_result"],
            status=row["status"],
            failure_note=row["failure_note"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
