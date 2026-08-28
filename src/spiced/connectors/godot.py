"""Godot project folder detection (Market-Viability Roadmap, Phase 2).

Mirrors ``connectors.unity``'s shallow-detection shape exactly: check for the
folder/file Godot always creates, read a little optional metadata, never scan
recursively or launch the engine.

**Format verification.** ``project.godot`` is not a format stdlib
``configparser`` can parse unmodified -- verified directly against a real
Godot 4 project rather than assumed from documentation: fetched
``project.godot`` from the official ``godotengine/godot-demo-projects`` repo
(``2d/dodge_the_creeps``). That sample confirmed a bare ``config_version=5``
key appears *before* any ``[section]`` header (which ``configparser`` treats
as a hard error, ``MissingSectionHeaderError``, unless worked around), that
string values can span multiple physical lines when they contain an embedded
newline inside the quotes (``config/description="...\\n\\n..."``), and that
some values are themselves multi-line bracketed structures (per-action
``InputEventKey`` dictionaries under ``[input]``). None of that is
``configparser``-safe. This module never attempts a general parse -- it
extracts only the small, specific top-level fields it needs
(``config/name``, ``config/features``, ``run/main_scene``) with targeted
regex against the ``[application]`` section only, the same targeted-field
philosophy as ``connectors.unity_controller_scan``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

VALIDATION_VALID = "valid"
VALIDATION_INVALID = "invalid"

_PROJECT_FILE_NAME = "project.godot"
_SECTION_RE = re.compile(r"^\[(\w+)\]\s*$")
_NAME_RE = re.compile(r'^config/name="((?:[^"\\]|\\.)*)"')
_MAIN_SCENE_RE = re.compile(r'^run/main_scene="((?:[^"\\]|\\.)*)"')
# config/features=PackedStringArray("4.7") -- the first quoted entry is the
# engine version the project was last saved with; a project can list more
# than one feature tag, so only the first quoted string is taken.
_FEATURES_RE = re.compile(r'^config/features=PackedStringArray\("([^"]*)"')


@dataclass(frozen=True)
class GodotDetectionResult:
    is_valid: bool
    project_name: str | None
    godot_version: str | None
    main_scene: str | None
    warnings: list[str] = field(default_factory=list)

    @property
    def validation_status(self) -> str:
        return VALIDATION_VALID if self.is_valid else VALIDATION_INVALID

    def metadata(self) -> dict:
        """Small, safe metadata dict stored alongside the project -- same
        shape/purpose as ``UnityDetectionResult.metadata``."""
        data: dict = {}
        if self.godot_version:
            data["godot_version"] = self.godot_version
        if self.main_scene:
            data["main_scene"] = self.main_scene
        if self.warnings:
            data["warnings"] = self.warnings
        return data


def project_file_path(project_path: str | Path) -> Path:
    """The standard location of a Godot project's project file -- a single,
    shared place every feature that reads it agrees on, matching
    ``connectors.unity.manifest_path_for``'s role for Unity."""
    return Path(project_path) / _PROJECT_FILE_NAME


def detect_godot_project(folder: str | Path) -> GodotDetectionResult:
    """Inspect a folder and report whether it looks like a Godot project.

    A project is valid when ``project.godot`` exists at its root -- Godot has
    no equivalent of Unity's separate ``Assets/``/``ProjectSettings/`` folder
    pair; the single project file at the root is the one required marker.
    """
    path = Path(folder)
    warnings: list[str] = []

    if not path.exists() or not path.is_dir():
        return GodotDetectionResult(
            is_valid=False,
            project_name=None,
            godot_version=None,
            main_scene=None,
            warnings=["The selected path does not exist or is not a folder."],
        )

    project_file = project_file_path(path)
    if not project_file.is_file():
        warnings.append("Missing a 'project.godot' file, which every Godot project has.")
        return GodotDetectionResult(
            is_valid=False,
            project_name=None,
            godot_version=None,
            main_scene=None,
            warnings=warnings,
        )

    fields = _read_application_fields(project_file)
    return GodotDetectionResult(
        is_valid=True,
        project_name=fields.get("name") or path.name or None,
        godot_version=fields.get("version"),
        main_scene=fields.get("main_scene"),
        warnings=warnings,
    )


def _read_application_fields(project_file: Path) -> dict[str, str]:
    """Best-effort extraction of ``config/name``, ``config/features``, and
    ``run/main_scene`` from the ``[application]`` section only. Never
    raises -- an unreadable or malformed project file just yields an empty
    dict, matching ``connectors.unity``'s "optional metadata" treatment of
    ``ProjectVersion.txt``."""
    try:
        text = project_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    fields: dict[str, str] = {}
    in_application = False
    for line in text.splitlines():
        section_match = _SECTION_RE.match(line)
        if section_match:
            in_application = section_match.group(1) == "application"
            continue
        if not in_application:
            continue
        if (m := _NAME_RE.match(line)) is not None:
            fields["name"] = m.group(1)
        elif (m := _MAIN_SCENE_RE.match(line)) is not None:
            fields["main_scene"] = m.group(1)
        elif (m := _FEATURES_RE.match(line)) is not None:
            fields["version"] = m.group(1)
    return fields
