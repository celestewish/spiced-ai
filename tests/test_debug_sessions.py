from spiced.storage.database import Database
from spiced.storage.debug_sessions import DebugSessionRepository
from spiced.storage.projects import ProjectRepository


def _setup():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    sessions = DebugSessionRepository(db)
    project = projects.create("Moonlit Depths", engine="Unity")
    return sessions, project


def test_create_and_get_session():
    sessions, project = _setup()
    created = sessions.create(
        project_id=project.id,
        source_type="paste",
        summary="Likely a null reference on the health component.",
        detected_error_type="NullReferenceException",
        detected_file="HealthPickup.cs",
        detected_line=24,
        raw_excerpt="NullReferenceException: ...",
        suggested_next_steps=["Check the Inspector", "Verify the prefab reference"],
        provider="mock",
    )
    assert created.id > 0
    fetched = sessions.get(created.id)
    assert fetched.detected_error_type == "NullReferenceException"
    assert fetched.detected_line == 24
    assert fetched.suggested_next_steps == ["Check the Inspector", "Verify the prefab reference"]


def test_list_for_project_newest_first():
    sessions, project = _setup()
    sessions.create(project_id=project.id, source_type="paste", summary="first")
    sessions.create(project_id=project.id, source_type="paste", summary="second")
    rows = sessions.list_for_project(project.id)
    assert [r.summary for r in rows] == ["second", "first"]


def test_next_steps_empty_when_none():
    sessions, project = _setup()
    created = sessions.create(project_id=project.id, source_type="paste", summary="none")
    assert sessions.get(created.id).suggested_next_steps == []
