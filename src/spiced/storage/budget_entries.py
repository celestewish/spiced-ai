"""Budget/Runway Tracker persistence.

Purely local, project-scoped bookkeeping of the studio's own recurring
costs plus a single "available funds" figure per project -- this is not
Spiced's own billing (Spiced has none, anywhere; see core.budget_tracker).
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database

FREQUENCY_WEEKLY = "weekly"
FREQUENCY_MONTHLY = "monthly"
FREQUENCY_YEARLY = "yearly"
FREQUENCIES = (FREQUENCY_WEEKLY, FREQUENCY_MONTHLY, FREQUENCY_YEARLY)


@dataclass(frozen=True)
class BudgetEntry:
    id: int
    project_id: int
    name: str
    amount: float
    frequency: str
    created_at: str
    updated_at: str


class BudgetRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- Recurring cost entries ---------------------------------------------

    def create(
        self, project_id: int, name: str, amount: float, frequency: str
    ) -> BudgetEntry:
        new_id = self._db.execute(
            "INSERT INTO budget_entries (project_id, name, amount, frequency) VALUES (?, ?, ?, ?)",
            (project_id, name, amount, frequency),
        )
        return self.get(new_id)

    def update(self, entry_id: int, name: str, amount: float, frequency: str) -> BudgetEntry:
        self._db.execute(
            "UPDATE budget_entries SET name = ?, amount = ?, frequency = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (name, amount, frequency, entry_id),
        )
        return self.get(entry_id)

    def delete(self, entry_id: int) -> None:
        self._db.execute("DELETE FROM budget_entries WHERE id = ?", (entry_id,))

    def get(self, entry_id: int) -> BudgetEntry:
        row = self._db.query_one("SELECT * FROM budget_entries WHERE id = ?", (entry_id,))
        if row is None:
            raise KeyError(f"No budget entry with id {entry_id}")
        return self._to_entry(row)

    def list_for_project(self, project_id: int) -> list[BudgetEntry]:
        rows = self._db.query_all(
            "SELECT * FROM budget_entries WHERE project_id = ? ORDER BY created_at ASC, id ASC",
            (project_id,),
        )
        return [self._to_entry(r) for r in rows]

    @staticmethod
    def _to_entry(row) -> BudgetEntry:
        return BudgetEntry(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"],
            amount=row["amount"],
            frequency=row["frequency"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Available funds (one figure per project) ---------------------------

    def get_available_funds(self, project_id: int) -> float:
        row = self._db.query_one(
            "SELECT amount FROM budget_available_funds WHERE project_id = ?", (project_id,)
        )
        return float(row["amount"]) if row is not None else 0.0

    def set_available_funds(self, project_id: int, amount: float) -> None:
        self._db.execute(
            "INSERT INTO budget_available_funds (project_id, amount, updated_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(project_id) DO UPDATE SET amount = excluded.amount, "
            "updated_at = excluded.updated_at",
            (project_id, amount),
        )
