"""Project use-cases exposed to the UI."""

from __future__ import annotations

import uuid

from spiced.connectors.unity import UnityDetectionResult, detect_unity_project
from spiced.storage.projects import Project, ProjectRepository


class ProjectsService:
    def __init__(self, repo: ProjectRepository) -> None:
        self._repo = repo

    def create_project(
        self,
        name: str,
        engine: str = "Unity",
        path: str | None = None,
        description: str | None = None,
    ) -> Project:
        return self._repo.create(name=name, engine=engine, path=path, description=description)

    def list_projects(self) -> list[Project]:
        return self._repo.list_all()

    def get_project(self, project_id: int) -> Project:
        return self._repo.get(project_id)

    def attach_unity_folder(
        self, project_id: int, folder: str
    ) -> tuple[Project, UnityDetectionResult]:
        """Validate a Unity folder and store its path, status, and metadata.

        The result is stored whether or not the folder is valid, so the UI can
        show a friendly warning while still remembering the developer's choice.
        """
        detection = detect_unity_project(folder)
        project = self._repo.set_unity_folder(
            project_id,
            path=str(folder),
            validation_status=detection.validation_status,
            metadata=detection.metadata() or None,
        )
        return project, detection

    def set_unity_test_run_settings(
        self, project_id: int, enabled: bool, editor_path_override: str | None = None
    ) -> Project:
        """Opt a project in/out of Spiced launching its Unity Editor to run tests.

        Off by default. This is the one place Spiced executes an external
        engine process rather than just parsing text — everything else stays
        paste/import only.
        """
        return self._repo.set_unity_test_run_settings(project_id, enabled, editor_path_override)

    def ensure_project_uuid(self, project_id: int) -> str:
        """Return this project's stable cross-machine id, minting one on first use.

        Solo-Dev projects never call this — it only runs the first time a
        project is linked to a Small-Team Mode team, so purely local projects
        never gain a project_uuid.
        """
        project = self._repo.get(project_id)
        if project.project_uuid:
            return project.project_uuid
        new_uuid = str(uuid.uuid4())
        self._repo.set_project_uuid(project_id, new_uuid)
        return new_uuid
