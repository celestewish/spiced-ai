"""Key-scene config persistence for Visual Regression Testing
(Implementation Bible, Feature 2). Each row names one scene + a marker
GameObject the capture camera snaps to -- see
``docs/visual_regression_capture_hook.md`` for the convention.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.storage.database import Database


@dataclass(frozen=True)
class KeySceneRecord:
    id: int
    project_id: int
    scene_path: str
    label: str
    marker_name: str
    created_at: str


class VisualRegressionKeySceneRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(
        self, project_id: int, scene_path: str, label: str, marker_name: str
    ) -> KeySceneRecord:
        scene_path = scene_path.strip()
        label = label.strip()
        marker_name = marker_name.strip()
        if not scene_path or not label or not marker_name:
            raise ValueError("scene_path, label, and marker_name are all required.")
        new_id = self._db.execute(
            "INSERT INTO visual_regression_key_scenes "
            "(project_id, scene_path, label, marker_name) VALUES (?, ?, ?, ?)",
            (project_id, scene_path, label, marker_name),
        )
        return self.get(new_id)

    def get(self, key_scene_id: int) -> KeySceneRecord:
        row = self._db.query_one(
            "SELECT * FROM visual_regression_key_scenes WHERE id = ?", (key_scene_id,)
        )
        if row is None:
            raise KeyError(f"No key scene with id {key_scene_id}")
        return self._to_record(row)

    def list_for_project(self, project_id: int) -> list[KeySceneRecord]:
        rows = self._db.query_all(
            "SELECT * FROM visual_regression_key_scenes WHERE project_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (project_id,),
        )
        return [self._to_record(r) for r in rows]

    def delete(self, key_scene_id: int) -> None:
        self._db.execute(
            "DELETE FROM visual_regression_key_scenes WHERE id = ?", (key_scene_id,)
        )

    @staticmethod
    def _to_record(row) -> KeySceneRecord:
        return KeySceneRecord(
            id=row["id"],
            project_id=row["project_id"],
            scene_path=row["scene_path"],
            label=row["label"],
            marker_name=row["marker_name"],
            created_at=row["created_at"],
        )
