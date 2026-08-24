"""Unreal project folder detection (Market-Viability Roadmap, Phase 3).

Mirrors ``connectors.unity``/``connectors.godot``'s shallow-detection shape:
check for the marker file every Unreal project has, read a little optional
metadata, never scan recursively or launch the engine.

Unlike ``project.godot`` (which needed a hand-rolled parser -- see that
module's docstring), a ``.uproject`` file is genuinely, simply JSON --
verified against a real one fetched from a public repo
(``life-exe/UnrealTPSGame/TPS.uproject``), which confirmed the top-level
``FileVersion``/``EngineAssociation``/``Modules`` shape and that stdlib
``json`` parses it directly with no quirks to work around.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

VALIDATION_VALID = "valid"
VALIDATION_INVALID = "invalid"

_UPROJECT_GLOB = "*.uproject"


@dataclass(frozen=True)
class UnrealDetectionResult:
    is_valid: bool
    project_name: str | None
    engine_association: str | None
    warnings: list[str] = field(default_factory=list)

    @property
    def validation_status(self) -> str:
        return VALIDATION_VALID if self.is_valid else VALIDATION_INVALID

    def metadata(self) -> dict:
        """Small, safe metadata dict stored alongside the project -- same
        shape/purpose as ``UnityDetectionResult.metadata``/
        ``GodotDetectionResult.metadata``."""
        data: dict = {}
        if self.engine_association:
            data["engine_association"] = self.engine_association
        if self.warnings:
            data["warnings"] = self.warnings
        return data


def find_uproject_file(project_path: str | Path) -> Path | None:
    """The project's ``<Name>.uproject`` file at its root, or ``None`` if
    there isn't exactly one. Unlike Unity's fixed ``Packages/manifest.json``
    path or Godot's fixed ``project.godot`` name, Unreal's project file is
    named after the project itself, so it has to be discovered by
    extension rather than by a known filename."""
    root = Path(project_path)
    if not root.is_dir():
        return None
    matches = sorted(root.glob(_UPROJECT_GLOB))
    return matches[0] if len(matches) == 1 else None


def detect_unreal_project(folder: str | Path) -> UnrealDetectionResult:
    """Inspect a folder and report whether it looks like an Unreal project.

    A project is valid when exactly one ``*.uproject`` file exists at the
    folder's root and it parses as JSON with the fields a real ``.uproject``
    always has.
    """
    path = Path(folder)
    warnings: list[str] = []

    if not path.exists() or not path.is_dir():
        return UnrealDetectionResult(
            is_valid=False,
            project_name=None,
            engine_association=None,
            warnings=["The selected path does not exist or is not a folder."],
        )

    uproject_matches = sorted(path.glob(_UPROJECT_GLOB))
    if not uproject_matches:
        return UnrealDetectionResult(
            is_valid=False,
            project_name=None,
            engine_association=None,
            warnings=["Missing a '<Name>.uproject' file, which every Unreal project has."],
        )
    if len(uproject_matches) > 1:
        return UnrealDetectionResult(
            is_valid=False,
            project_name=None,
            engine_association=None,
            warnings=[
                "Found more than one '.uproject' file at this folder's root — expected "
                "exactly one."
            ],
        )

    uproject_file = uproject_matches[0]
    try:
        data = json.loads(uproject_file.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return UnrealDetectionResult(
            is_valid=False,
            project_name=None,
            engine_association=None,
            warnings=[f"'{uproject_file.name}' couldn't be read as valid JSON."],
        )
    if not isinstance(data, dict) or "FileVersion" not in data:
        warnings.append(
            f"'{uproject_file.name}' doesn't look like a standard Unreal project file "
            "(missing FileVersion)."
        )

    return UnrealDetectionResult(
        is_valid=not warnings,
        project_name=uproject_file.stem,
        engine_association=data.get("EngineAssociation") if isinstance(data, dict) else None,
        warnings=warnings,
    )
