"""Project use-cases exposed to the UI."""

from __future__ import annotations

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
