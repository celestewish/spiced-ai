"""Tests for core.budget_tracker: CRUD, monthly-equivalent conversion, runway math."""

from __future__ import annotations

import pytest

from spiced.core.budget_tracker import (
    BudgetTrackerService,
    RunwaySummary,
    compute_runway,
    monthly_equivalent,
)
from spiced.storage.budget_entries import BudgetRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _svc():
    db = Database(":memory:")
    return BudgetTrackerService(BudgetRepository(db)), ProjectRepository(db)


def test_monthly_equivalent_monthly_is_unchanged():
    assert monthly_equivalent(500, "monthly") == 500


def test_monthly_equivalent_weekly_converts_correctly():
    assert monthly_equivalent(100, "weekly") == pytest.approx(100 * 52 / 12)


def test_monthly_equivalent_yearly_converts_correctly():
    assert monthly_equivalent(1200, "yearly") == pytest.approx(100)


def test_compute_runway_simple_monthly_case():
    from spiced.storage.budget_entries import BudgetEntry

    entries = [
        BudgetEntry(
            id=1, project_id=1, name="Contractor", amount=500, frequency="monthly",
            created_at="", updated_at="",
        )
    ]
    summary = compute_runway(1000, entries)
    assert summary.monthly_burn == 500
    assert summary.runway_months == pytest.approx(2.0)
    assert not summary.is_indefinite
    assert not summary.is_depleted


def test_compute_runway_yearly_case():
    from spiced.storage.budget_entries import BudgetEntry

    entries = [
        BudgetEntry(
            id=1, project_id=1, name="Server hosting", amount=1200, frequency="yearly",
            created_at="", updated_at="",
        )
    ]
    summary = compute_runway(1200, entries)
    assert summary.monthly_burn == pytest.approx(100)
    assert summary.runway_months == pytest.approx(12.0)


def test_compute_runway_weekly_case():
    from spiced.storage.budget_entries import BudgetEntry

    entries = [
        BudgetEntry(
            id=1, project_id=1, name="Freelancer", amount=100, frequency="weekly",
            created_at="", updated_at="",
        )
    ]
    summary = compute_runway(1000, entries)
    expected_burn = 100 * 52 / 12
    assert summary.monthly_burn == pytest.approx(expected_burn)
    assert summary.runway_months == pytest.approx(1000 / expected_burn)


def test_compute_runway_zero_burn_is_indefinite():
    summary = compute_runway(1000, [])
    assert summary.monthly_burn == 0
    assert summary.runway_months is None
    assert summary.is_indefinite


def test_compute_runway_zero_funds_with_burn_is_depleted():
    from spiced.storage.budget_entries import BudgetEntry

    entries = [
        BudgetEntry(
            id=1, project_id=1, name="Tools", amount=50, frequency="monthly",
            created_at="", updated_at="",
        )
    ]
    summary = compute_runway(0, entries)
    assert summary.runway_months == 0
    assert summary.is_depleted


def test_add_entry_rejects_empty_name():
    service, projects = _svc()
    project = projects.create("Moonlit Depths")
    with pytest.raises(ValueError):
        service.add_entry(project.id, "  ", 10, "monthly")


def test_add_entry_rejects_unknown_frequency():
    service, projects = _svc()
    project = projects.create("Moonlit Depths")
    with pytest.raises(ValueError):
        service.add_entry(project.id, "Tools", 10, "daily")


def test_add_entry_rejects_negative_amount():
    service, projects = _svc()
    project = projects.create("Moonlit Depths")
    with pytest.raises(ValueError):
        service.add_entry(project.id, "Tools", -5, "monthly")


def test_crud_round_trip():
    service, projects = _svc()
    project = projects.create("Moonlit Depths")
    entry = service.add_entry(project.id, "Unity Pro seat", 185, "monthly")
    assert entry.name == "Unity Pro seat"

    updated = service.update_entry(entry.id, "Unity Pro seat (annual)", 1850, "yearly")
    assert updated.amount == 1850
    assert updated.frequency == "yearly"

    assert len(service.list_entries(project.id)) == 1
    service.delete_entry(entry.id)
    assert service.list_entries(project.id) == []


def test_available_funds_round_trip():
    service, projects = _svc()
    project = projects.create("Moonlit Depths")
    assert service.get_available_funds(project.id) == 0.0
    service.set_available_funds(project.id, 2500)
    assert service.get_available_funds(project.id) == 2500


def test_set_available_funds_rejects_negative():
    service, projects = _svc()
    project = projects.create("Moonlit Depths")
    with pytest.raises(ValueError):
        service.set_available_funds(project.id, -1)


def test_runway_end_to_end_via_service():
    service, projects = _svc()
    project = projects.create("Moonlit Depths")
    service.set_available_funds(project.id, 3000)
    service.add_entry(project.id, "Contractor", 1000, "monthly")
    service.add_entry(project.id, "Tools", 200, "monthly")

    summary = service.runway(project)
    assert isinstance(summary, RunwaySummary)
    assert summary.monthly_burn == pytest.approx(1200)
    assert summary.runway_months == pytest.approx(2.5)
    assert summary.entry_count == 2
