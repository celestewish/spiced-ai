"""Resolving the Godot/Unreal executables a build or test run needs.

Unlike Unity (``core.unity_test_runner.resolve_unity_editor``, which can
auto-discover an installed Editor via Unity Hub's documented CLI), there is
no Hub-equivalent for either Godot or Unreal -- no local registry of
installed versions to query. Both engines require a manual, explicit path
this phase, reusing ``Project.unity_editor_path_override`` (a generic
nullable string column, despite its Unity-flavored name) as the one place
that path is stored, same as Unity already does.

Godot's override is a direct path to the ``godot``/``godot.exe`` executable.
Unreal's is different in shape: an *engine install root* folder (e.g.
``C:\\Program Files\\Epic Games\\UE_5.3``), since a build needs
``RunUAT.bat``/``.sh`` and a test run needs ``UnrealEditor-Cmd.exe`` --
two different binaries under one install, both derived from the same root
here rather than asking the developer to configure each separately.

``find_installed_unreal_engines`` and ``find_godot_on_path`` below (Connect-
a-Project Setup Simplification spec, Finding 2) don't change any of that --
the override is still the only thing ``resolve_godot_executable``/
``resolve_unreal_uat``/``resolve_unreal_editor_cmd`` ever read. They exist
purely to help the UI *suggest* a value for that override before falling
back to an empty manual browse dialog; the developer still has to click
something to accept a suggestion (see ``ui.screens.projects``), same as
every other "opt-in, never silent" auto-detection in this codebase.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def resolve_godot_executable(override_path: str | None) -> str | None:
    """Just validates the configured path -- there is no auto-detect to
    fall back to (see module docstring)."""
    if not override_path:
        return None
    return override_path if Path(override_path).is_file() else None


def resolve_unreal_uat(engine_root_override: str | None) -> str | None:
    """``RunUAT.bat`` under ``<engine root>/Engine/Build/BatchFiles/``.

    ``.bat`` only -- this app's own conventions are Windows-first (see
    e.g. ``core.unity_test_runner``'s Windows-specific Editor-discovery
    paths); a ``.sh`` variant would be the natural follow-up for Linux/macOS
    support, not attempted here."""
    if not engine_root_override:
        return None
    uat = Path(engine_root_override) / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
    return str(uat) if uat.is_file() else None


def resolve_unreal_editor_cmd(engine_root_override: str | None) -> str | None:
    """``UnrealEditor-Cmd.exe`` under ``<engine root>/Engine/Binaries/Win64/``."""
    if not engine_root_override:
        return None
    editor_cmd = (
        Path(engine_root_override) / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    )
    return str(editor_cmd) if editor_cmd.is_file() else None


def find_installed_unreal_engines() -> dict[str, str]:
    """Version string (e.g. ``"5.3"``) -> engine install root, read from the
    Epic Games Launcher's own install manifest.

    ``%ProgramData%\\Epic\\UnrealEngineLauncher\\LauncherInstalled.dat`` is a
    small JSON file the Launcher writes for every engine version it manages:
    ``{"InstallationList": [{"InstallLocation": "...", "AppName": "UE_5.3",
    ...}, ...]}``. Best-effort, like every other detector in this codebase
    (e.g. ``connectors.unity``'s optional-metadata reads) -- a missing,
    unreadable, or malformed manifest just yields ``{}`` rather than
    raising, since not finding it is the expected case for anyone who
    installed Unreal outside the Epic Games Launcher (e.g. building from
    source) or isn't on Windows at all.
    """
    program_data = os.environ.get("ProgramData")
    if not program_data:
        return {}
    manifest = Path(program_data) / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat"
    try:
        raw = manifest.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}

    installs = data.get("InstallationList") if isinstance(data, dict) else None
    if not isinstance(installs, list):
        return {}

    found: dict[str, str] = {}
    for entry in installs:
        if not isinstance(entry, dict):
            continue
        app_name = entry.get("AppName")
        location = entry.get("InstallLocation")
        if not isinstance(app_name, str) or not isinstance(location, str) or not location:
            continue
        # AppName is "UE_5.3" for a normal engine install -- strip the
        # prefix to leave the bare version string
        # UnrealDetectionResult.engine_association is already parsed as
        # (e.g. "5.3" from a .uproject's "EngineAssociation"), since that's
        # what callers actually compare this dict's keys against.
        version = app_name[len("UE_") :] if app_name.startswith("UE_") else app_name
        found[version] = location
    return found


def find_godot_on_path() -> str | None:
    """A ``godot``/``godot.exe`` resolvable on ``PATH``, or ``None``.

    Free, stdlib-only (``shutil.which``) -- same "no extra dependency"
    philosophy as this codebase's Discord integration. Covers anyone who
    installed Godot via a package manager (Scoop/Chocolatey/winget) or
    added it to ``PATH`` by hand; a portable, unregistered Godot download
    still needs the manual override, same as before.
    """
    return shutil.which("godot") or shutil.which("godot.exe")
