"""Project use-cases exposed to the UI."""

from __future__ import annotations

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
