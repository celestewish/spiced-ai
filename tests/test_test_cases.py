import pytest

from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.test_cases import TestCaseRepository


def _setup():
    db = Database(":memory:")
    cases = TestCaseRepository(db)
    project = ProjectRepository(db).create("Moonlit Depths", engine="Unity")
    return cases, project


def test_create_defaults_and_fields():
    cases, project = _setup()
    case = cases.create(
        project_id=project.id,
        title="Player takes damage from spikes",
        category="Gameplay",
        priority="High",
        steps="Walk onto spikes",
        expected_result="Health decreases",
    )
    assert case.id > 0
    assert case.title == "Player takes damage from spikes"
    assert case.category == "Gameplay"
    assert case.priority == "High"
    assert case.status == "Not Run"
    assert case.failure_note is None


def test_create_coerces_unknown_values_to_defaults():
    cases, project = _setup()
    case = cases.create(
        project_id=project.id,
        title="Odd case",
        category="Nonsense",
        priority="Whenever",
        status="Weird",
    )
    assert case.category == "General"
    assert case.priority == "Medium"
    assert case.status == "Not Run"


def test_create_rejects_empty_title():
    cases, project = _setup()
    with pytest.raises(ValueError):
        cases.create(project_id=project.id, title="   ")


def test_set_status_keeps_failure_note_only_on_fail():
    cases, project = _setup()
    case = cases.create(project_id=project.id, title="Health pickup restores health")

    failed = cases.set_status(case.id, "Fail", "Health stayed at 0")
    assert failed.status == "Fail"
    assert failed.failure_note == "Health stayed at 0"

    passed = cases.set_status(case.id, "Pass", "leftover note")
    assert passed.status == "Pass"
    assert passed.failure_note is None


def test_set_status_rejects_unknown_status():
    cases, project = _setup()
    case = cases.create(project_id=project.id, title="Case")
    with pytest.raises(ValueError):
        cases.set_status(case.id, "Exploded")


def test_update_changes_all_editable_fields():
    cases, project = _setup()
    case = cases.create(project_id=project.id, title="Old title", category="UI")
    updated = cases.update(
        case.id,
        title="New title",
        category="Gameplay",
        priority="Critical",
        steps="do a thing",
        expected_result="the thing happens",
        status="Fail",
        failure_note="did not happen",
    )
    assert updated.title == "New title"
    assert updated.category == "Gameplay"
    assert updated.priority == "Critical"
    assert updated.steps == "do a thing"
    assert updated.expected_result == "the thing happens"
    assert updated.status == "Fail"
    assert updated.failure_note == "did not happen"


def test_update_clears_failure_note_when_not_fail():
    cases, project = _setup()
    case = cases.create(project_id=project.id, title="Case")
    cases.update(case.id, title="Case", status="Fail", failure_note="broke")
    cleared = cases.update(case.id, title="Case", status="Pass", failure_note="stale")
    assert cleared.failure_note is None


def test_update_rejects_empty_title():
    cases, project = _setup()
    case = cases.create(project_id=project.id, title="Case")
    with pytest.raises(ValueError):
        cases.update(case.id, title="   ")


def test_delete_removes_only_the_case():
    cases, project = _setup()
    keep = cases.create(project_id=project.id, title="Keep me")
    drop = cases.create(project_id=project.id, title="Drop me")
    cases.delete(drop.id)
    remaining = cases.list_for_project(project.id)
    assert [c.title for c in remaining] == ["Keep me"]
    with pytest.raises(KeyError):
        cases.get(drop.id)
    assert cases.get(keep.id).title == "Keep me"


def test_list_is_project_scoped():
    db = Database(":memory:")
    cases = TestCaseRepository(db)
    projects = ProjectRepository(db)
    p1 = projects.create("Game One", engine="Unity")
    p2 = projects.create("Game Two", engine="Unity")
    cases.create(project_id=p1.id, title="Only in one")
    cases.create(project_id=p2.id, title="Only in two")

    listed = cases.list_for_project(p1.id)
    assert [c.title for c in listed] == ["Only in one"]
