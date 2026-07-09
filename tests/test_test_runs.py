from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.test_runs import TestRunRepository


def _setup():
    db = Database(":memory:")
    runs = TestRunRepository(db)
    project = ProjectRepository(db).create("Moonlit Depths", engine="Unity")
    return runs, project


def test_create_round_trips_summary_and_checklist():
    runs, project = _setup()
    run = runs.create(
        project_id=project.id,
        source_type="paste",
        source_filename=None,
        raw_excerpt="PASS a\nFAIL b",
        parsed_summary={"total": 2, "passed": 1, "failed": 1},
        ai_summary="One failure to inspect.",
        retest_checklist=["Re-run b", "Check the collider"],
        provider="mock",
    )
    fetched = runs.get(run.id)
    assert fetched.parsed_summary == {"total": 2, "passed": 1, "failed": 1}
    assert fetched.retest_checklist == ["Re-run b", "Check the collider"]
    assert fetched.provider == "mock"


def test_empty_json_properties_default_gracefully():
    runs, project = _setup()
    run = runs.create(project_id=project.id, source_type="paste")
    assert run.parsed_summary == {}
    assert run.retest_checklist == []


def test_list_newest_first_and_project_scoped():
    db = Database(":memory:")
    runs = TestRunRepository(db)
    projects = ProjectRepository(db)
    p1 = projects.create("Game One", engine="Unity")
    p2 = projects.create("Game Two", engine="Unity")
    runs.create(project_id=p1.id, source_type="paste", ai_summary="first")
    runs.create(project_id=p1.id, source_type="paste", ai_summary="second")
    runs.create(project_id=p2.id, source_type="paste", ai_summary="other project")

    listed = runs.list_for_project(p1.id)
    assert [r.ai_summary for r in listed] == ["second", "first"]
