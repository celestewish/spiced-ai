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


def test_attach_unity_folder_valid(tmp_path):
    (tmp_path / "Assets").mkdir()
    (tmp_path / "ProjectSettings").mkdir()
    service = _service()
    project = service.create_project("Moonlit Depths")
    updated, detection = service.attach_unity_folder(project.id, str(tmp_path))
    assert detection.is_valid
    assert updated.path == str(tmp_path)
    assert updated.is_valid_unity


def test_attach_unity_folder_invalid_still_saves_path(tmp_path):
    service = _service()
    project = service.create_project("Not Unity")
    updated, detection = service.attach_unity_folder(project.id, str(tmp_path))
    assert not detection.is_valid
    assert updated.path == str(tmp_path)
    assert not updated.is_valid_unity


def test_unity_test_run_settings_default_off():
    service = _service()
    project = service.create_project("Moonlit Depths")
    assert project.unity_test_run_enabled is False
    assert project.unity_editor_path_override is None


def test_unity_test_run_settings_can_be_enabled_with_override():
    service = _service()
    project = service.create_project("Moonlit Depths")
    updated = service.set_unity_test_run_settings(
        project.id, True, editor_path_override=r"C:\Unity\2022.3.10f1\Editor\Unity.exe"
    )
    assert updated.unity_test_run_enabled is True
    assert updated.unity_editor_path_override == r"C:\Unity\2022.3.10f1\Editor\Unity.exe"


def test_unity_test_run_settings_can_be_disabled_again():
    service = _service()
    project = service.create_project("Moonlit Depths")
    service.set_unity_test_run_settings(project.id, True, r"C:\Unity\Unity.exe")
    disabled = service.set_unity_test_run_settings(project.id, False, None)
    assert disabled.unity_test_run_enabled is False
    assert disabled.unity_editor_path_override is None


def test_project_uuid_is_none_until_linked_to_a_team():
    service = _service()
    project = service.create_project("Moonlit Depths")
    assert project.project_uuid is None


def test_ensure_project_uuid_mints_and_persists():
    service = _service()
    project = service.create_project("Moonlit Depths")
    minted = service.ensure_project_uuid(project.id)
    assert minted
    assert service.get_project(project.id).project_uuid == minted


def test_ensure_project_uuid_is_stable_across_calls():
    service = _service()
    project = service.create_project("Moonlit Depths")
    first = service.ensure_project_uuid(project.id)
    second = service.ensure_project_uuid(project.id)
    assert first == second
