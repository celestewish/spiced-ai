"""Reference-palette persistence for Texture & Palette Drift Detection
(Implementation Bible, Feature 4). Each row is one hex color in a project's
established style reference -- either added directly, or materialized from
a reference folder (``automation.palette_drift.PaletteDriftService.
set_reference_from_folder``, which replaces the whole set at once).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from spiced.storage.database import Database

_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")


@dataclass(frozen=True)
class PaletteReferenceColor:
    id: int
    project_id: int
    hex_color: str
    created_at: str


class PaletteReferenceColorRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, project_id: int, hex_color: str) -> PaletteReferenceColor:
        match = _HEX_RE.match(hex_color.strip())
        if not match:
            raise ValueError(f'"{hex_color}" is not a 6-digit hex color, e.g. "#3366CC".')
        normalized = f"#{match.group(1).lower()}"
        new_id = self._db.execute(
            "INSERT INTO palette_reference_colors (project_id, hex_color) VALUES (?, ?)",
            (project_id, normalized),
        )
        return self.get(new_id)

    def get(self, color_id: int) -> PaletteReferenceColor:
        row = self._db.query_one(
            "SELECT * FROM palette_reference_colors WHERE id = ?", (color_id,)
        )
        if row is None:
            raise KeyError(f"No palette reference color with id {color_id}")
        return self._to_record(row)

    def list_for_project(self, project_id: int) -> list[PaletteReferenceColor]:
        rows = self._db.query_all(
            "SELECT * FROM palette_reference_colors WHERE project_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (project_id,),
        )
        return [self._to_record(r) for r in rows]

    def delete(self, color_id: int) -> None:
        self._db.execute("DELETE FROM palette_reference_colors WHERE id = ?", (color_id,))

    def clear(self, project_id: int) -> None:
        self._db.execute(
            "DELETE FROM palette_reference_colors WHERE project_id = ?", (project_id,)
        )

    @staticmethod
    def _to_record(row) -> PaletteReferenceColor:
        return PaletteReferenceColor(
            id=row["id"],
            project_id=row["project_id"],
            hex_color=row["hex_color"],
            created_at=row["created_at"],
        )
