"""Budget/Runway Tracker use-case (Phase H, section 7 part 2, Phase 2 tier).

Purely local, offline bookkeeping of the *studio's own* recurring costs
(subscriptions, contractor pay, tools) plus a manually-entered "funds
available" figure -- this tracks the developer's real-world money, not
Spiced's own billing (Spiced has no real billing anywhere, per the app's
existing design principle; this feature must never blur that line).

The runway calculation is pure arithmetic and needs no AI provider at all --
the whole feature works with zero provider configured, the same philosophy
as Code Health's local metrics. No AI summary is offered here: the numbers
speak for themselves and a narrative pass over three numbers wouldn't add
anything a provider could meaningfully verify (the spec explicitly calls an
AI-phrased summary optional, not required).
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.budget_entries import (
    FREQUENCIES,
    FREQUENCY_MONTHLY,
    FREQUENCY_WEEKLY,
    FREQUENCY_YEARLY,
    BudgetEntry,
    BudgetRepository,
)
from spiced.storage.projects import Project

# Weeks in a year / months in a year -- the standard conversion factor used
# to turn a weekly recurring cost into its monthly equivalent.
_WEEKS_PER_MONTH = 52 / 12


def monthly_equivalent(amount: float, frequency: str) -> float:
    """Convert a recurring cost of any supported frequency to its monthly equivalent."""
    if frequency == FREQUENCY_WEEKLY:
        return amount * _WEEKS_PER_MONTH
    if frequency == FREQUENCY_YEARLY:
        return amount / 12
    return amount  # FREQUENCY_MONTHLY, and any unrecognized value defaults to as-is


@dataclass(frozen=True)
class RunwaySummary:
    available_funds: float
    monthly_burn: float
    entry_count: int
    runway_months: float | None  # None means indefinite (zero or negative burn)

    @property
    def is_indefinite(self) -> bool:
        return self.runway_months is None

    @property
    def is_depleted(self) -> bool:
        return self.runway_months is not None and self.runway_months <= 0


def compute_runway(available_funds: float, entries: list[BudgetEntry]) -> RunwaySummary:
    """Pure arithmetic: sum each entry's monthly-equivalent cost, then divide
    available funds by that total. Zero (or negative, which shouldn't
    normally happen) monthly burn means an indefinite runway, not a
    division-by-zero error or a misleading zero."""
    monthly_burn = sum(monthly_equivalent(e.amount, e.frequency) for e in entries)
    if monthly_burn <= 0:
        runway_months = None
    else:
        runway_months = max(available_funds, 0.0) / monthly_burn
    return RunwaySummary(
        available_funds=available_funds,
        monthly_burn=monthly_burn,
        entry_count=len(entries),
        runway_months=runway_months,
    )


class BudgetTrackerService:
    def __init__(self, repository: BudgetRepository) -> None:
        self._repo = repository

    # --- Recurring cost entries (simple CRUD) -------------------------------

    def add_entry(self, project_id: int, name: str, amount: float, frequency: str) -> BudgetEntry:
        name = name.strip()
        if not name:
            raise ValueError("A cost name is required.")
        if amount < 0:
            raise ValueError("Amount cannot be negative.")
        if frequency not in FREQUENCIES:
            raise ValueError(f"Unknown frequency: {frequency!r}. Expected one of {FREQUENCIES}.")
        return self._repo.create(project_id, name, amount, frequency)

    def update_entry(
        self, entry_id: int, name: str, amount: float, frequency: str
    ) -> BudgetEntry:
        name = name.strip()
        if not name:
            raise ValueError("A cost name is required.")
        if amount < 0:
            raise ValueError("Amount cannot be negative.")
        if frequency not in FREQUENCIES:
            raise ValueError(f"Unknown frequency: {frequency!r}. Expected one of {FREQUENCIES}.")
        return self._repo.update(entry_id, name, amount, frequency)

    def delete_entry(self, entry_id: int) -> None:
        self._repo.delete(entry_id)

    def list_entries(self, project_id: int) -> list[BudgetEntry]:
        return self._repo.list_for_project(project_id)

    # --- Available funds -----------------------------------------------------

    def get_available_funds(self, project_id: int) -> float:
        return self._repo.get_available_funds(project_id)

    def set_available_funds(self, project_id: int, amount: float) -> None:
        if amount < 0:
            raise ValueError("Available funds cannot be negative.")
        self._repo.set_available_funds(project_id, amount)

    # --- Runway ----------------------------------------------------------------

    def runway(self, project: Project) -> RunwaySummary:
        entries = self.list_entries(project.id)
        available = self.get_available_funds(project.id)
        return compute_runway(available, entries)


__all__ = [
    "FREQUENCIES",
    "FREQUENCY_MONTHLY",
    "FREQUENCY_WEEKLY",
    "FREQUENCY_YEARLY",
    "BudgetEntry",
    "BudgetTrackerService",
    "RunwaySummary",
    "compute_runway",
    "monthly_equivalent",
]
