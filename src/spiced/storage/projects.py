"""Project persistence (create / read)."""

from __future__ import annotations

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


class ProjectRepository:
    """Create and read game projects. No update/delete in Phase 0."""

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
        cur = self._db.conn.execute(
            "INSERT INTO projects (name, engine, path, description) VALUES (?, ?, ?, ?)",
            (name, engine, path, description),
        )
        self._db.conn.commit()
        return self.get(int(cur.lastrowid))

    def get(self, project_id: int) -> Project:
        row = self._db.conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"No project with id {project_id}")
        return self._to_project(row)

    def list_all(self) -> list[Project]:
        rows = self._db.conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC, id DESC"
        ).fetchall()
        return [self._to_project(r) for r in rows]

    @staticmethod
    def _to_project(row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            engine=row["engine"],
            path=row["path"],
            description=row["description"],
            created_at=row["created_at"],
        )
