"""Project persistence (create / read / Unity folder update)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    engine: str
    path: str | None
    description: str | None
    created_at: str
    validation_status: str | None = None
    engine_metadata_json: str | None = None

    @property
    def engine_metadata(self) -> dict:
        if not self.engine_metadata_json:
            return {}
        try:
            data = json.loads(self.engine_metadata_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def is_valid_unity(self) -> bool:
        return self.validation_status == "valid"


class ProjectRepository:
    """Create, read, and update the Unity folder details of game projects."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        name: str,
        engine: str = "Unity",
        path: str | None = None,
        description: str | None = None,
    ) -> Project:
        name = name.strip()
        if not name:
            raise ValueError("Project name cannot be empty.")
        new_id = self._db.execute(
            "INSERT INTO projects (name, engine, path, description) VALUES (?, ?, ?, ?)",
            (name, engine, path, description),
        )
        return self.get(new_id)

    def set_unity_folder(
        self,
        project_id: int,
        path: str,
        validation_status: str,
        metadata: dict | None = None,
    ) -> Project:
        metadata_json = json.dumps(metadata) if metadata else None
        self._db.execute(
            "UPDATE projects SET path = ?, validation_status = ?, engine_metadata_json = ? "
            "WHERE id = ?",
            (path, validation_status, metadata_json, project_id),
        )
        return self.get(project_id)

    def get(self, project_id: int) -> Project:
        row = self._db.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if row is None:
            raise KeyError(f"No project with id {project_id}")
        return self._to_project(row)

    def list_all(self) -> list[Project]:
        rows = self._db.query_all("SELECT * FROM projects ORDER BY created_at DESC, id DESC")
        return [self._to_project(r) for r in rows]

    @staticmethod
    def _to_project(row) -> Project:
        keys = row.keys()
        return Project(
            id=row["id"],
            name=row["name"],
            engine=row["engine"],
            path=row["path"],
            description=row["description"],
            created_at=row["created_at"],
            validation_status=row["validation_status"] if "validation_status" in keys else None,
            engine_metadata_json=(
                row["engine_metadata_json"] if "engine_metadata_json" in keys else None
            ),
        )
