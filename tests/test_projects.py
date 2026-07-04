import pytest

from spiced.core.projects_service import ProjectsService
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _service() -> ProjectsService:
    db = Database(":memory:")
    return ProjectsService(ProjectRepository(db))


def test_create_and_read_project():
    service = _service()
    created = service.create_project("Moonlit Depths", engine="Unity")
    assert created.id > 0
    assert created.name == "Moonlit Depths"
    assert created.engine == "Unity"

    projects = service.list_projects()
    assert len(projects) == 1
    assert projects[0].name == "Moonlit Depths"


def test_projects_listed_newest_first():
    service = _service()
    service.create_project("First")
    service.create_project("Second")
    names = [p.name for p in service.list_projects()]
    assert names[0] == "Second"


def test_empty_name_rejected():
    service = _service()
    with pytest.raises(ValueError):
        service.create_project("   ")
