"""Unity project folder detection.

Phase 1 is intentionally shallow: it checks for the folders Unity always
creates and reads a little optional metadata. It does NOT recursively scan the
project, execute Unity, or modify any files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

VALIDATION_VALID = "valid"
VALIDATION_INVALID = "invalid"
VALIDATION_UNKNOWN = "unknown"


@dataclass(frozen=True)
class UnityDetectionResult:
    is_valid: bool
    project_name: str | None
    manifest_path: str | None
    unity_version: str | None
    warnings: list[str] = field(default_factory=list)

    @property
    def validation_status(self) -> str:
        return VALIDATION_VALID if self.is_valid else VALIDATION_INVALID

    def metadata(self) -> dict:
        """Small, safe metadata dict stored alongside the project."""
        data: dict = {}
        if self.manifest_path:
            data["manifest_path"] = self.manifest_path
        if self.unity_version:
            data["unity_version"] = self.unity_version
        if self.warnings:
            data["warnings"] = self.warnings
        return data


def detect_unity_project(folder: str | Path) -> UnityDetectionResult:
    """Inspect a folder and report whether it looks like a Unity project.

    A project is valid when both ``Assets/`` and ``ProjectSettings/`` exist.
    ``Packages/manifest.json`` and ``ProjectVersion.txt`` are read only if
    present, and only as small optional metadata.
    """
    path = Path(folder)
    warnings: list[str] = []

    if not path.exists() or not path.is_dir():
        return UnityDetectionResult(
            is_valid=False,
            project_name=None,
            manifest_path=None,
            unity_version=None,
            warnings=["The selected path does not exist or is not a folder."],
        )

    has_assets = (path / "Assets").is_dir()
    has_project_settings = (path / "ProjectSettings").is_dir()

    if not has_assets:
        warnings.append("Missing an 'Assets' folder, which every Unity project has.")
    if not has_project_settings:
        warnings.append("Missing a 'ProjectSettings' folder, which every Unity project has.")

    is_valid = has_assets and has_project_settings

    manifest_path: str | None = None
    manifest = path / "Packages" / "manifest.json"
    if manifest.is_file():
        manifest_path = str(manifest)

    return UnityDetectionResult(
        is_valid=is_valid,
        project_name=path.name or None,
        manifest_path=manifest_path,
        unity_version=_read_unity_version(path),
        warnings=warnings,
    )


def _read_unity_version(path: Path) -> str | None:
    """Read the Unity editor version from ProjectSettings/ProjectVersion.txt."""
    version_file = path / "ProjectSettings" / "ProjectVersion.txt"
    if not version_file.is_file():
        return None
    try:
        for line in version_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("m_EditorVersion:"):
                return line.split(":", 1)[1].strip() or None
    except OSError:
        return None
    return None


def read_manifest_dependencies(manifest_path: str | Path) -> list[str]:
    """Return package names from a Unity manifest, or [] if unreadable.

    Best-effort and non-recursive; used only to show a little context.
    """
    try:
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    deps = data.get("dependencies", {})
    return sorted(deps.keys()) if isinstance(deps, dict) else []
