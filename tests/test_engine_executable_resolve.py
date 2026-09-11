"""core.engine_executable_resolve: resolving/suggesting the Godot/Unreal
executables a build or test run needs.

Connect-a-Project Setup Simplification spec, Finding 2 fix 4. The existing
``resolve_godot_executable``/``resolve_unreal_uat``/``resolve_unreal_editor_cmd``
(override validation) already had indirect coverage via the UI test
modules; this module is the first dedicated coverage for them plus the two
new auto-discovery helpers.
"""

from __future__ import annotations

import json

from spiced.core.engine_executable_resolve import (
    find_godot_on_path,
    find_installed_unreal_engines,
    resolve_godot_executable,
    resolve_unreal_editor_cmd,
    resolve_unreal_uat,
)

# --- resolve_godot_executable / resolve_unreal_uat / resolve_unreal_editor_cmd


def test_resolve_godot_executable_validates_the_override_path(tmp_path):
    exe = tmp_path / "godot.exe"
    exe.write_bytes(b"")

    assert resolve_godot_executable(str(exe)) == str(exe)
    assert resolve_godot_executable(str(tmp_path / "missing.exe")) is None
    assert resolve_godot_executable(None) is None


def test_resolve_unreal_uat_and_editor_cmd_derive_from_engine_root(tmp_path):
    root = tmp_path / "UE_5.3"
    uat = root / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
    uat.parent.mkdir(parents=True)
    uat.write_bytes(b"")
    editor_cmd = root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    editor_cmd.parent.mkdir(parents=True)
    editor_cmd.write_bytes(b"")

    assert resolve_unreal_uat(str(root)) == str(uat)
    assert resolve_unreal_editor_cmd(str(root)) == str(editor_cmd)


def test_resolve_unreal_paths_are_none_when_binaries_are_missing(tmp_path):
    root = tmp_path / "UE_5.3"
    root.mkdir()

    assert resolve_unreal_uat(str(root)) is None
    assert resolve_unreal_editor_cmd(str(root)) is None
    assert resolve_unreal_uat(None) is None
    assert resolve_unreal_editor_cmd(None) is None


# --- find_installed_unreal_engines -------------------------------------------


def _write_launcher_manifest(program_data, payload) -> None:
    manifest_dir = program_data / "Epic" / "UnrealEngineLauncher"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "LauncherInstalled.dat").write_text(json.dumps(payload), encoding="utf-8")


def test_find_installed_unreal_engines_parses_a_real_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("ProgramData", str(tmp_path))
    _write_launcher_manifest(
        tmp_path,
        {
            "InstallationList": [
                {"InstallLocation": r"C:\Program Files\Epic Games\UE_5.3", "AppName": "UE_5.3"},
                {"InstallLocation": r"C:\Program Files\Epic Games\UE_5.1", "AppName": "UE_5.1"},
            ]
        },
    )

    installs = find_installed_unreal_engines()

    assert installs == {
        "5.3": r"C:\Program Files\Epic Games\UE_5.3",
        "5.1": r"C:\Program Files\Epic Games\UE_5.1",
    }


def test_find_installed_unreal_engines_missing_env_var_returns_empty(monkeypatch):
    monkeypatch.delenv("ProgramData", raising=False)

    assert find_installed_unreal_engines() == {}


def test_find_installed_unreal_engines_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("ProgramData", str(tmp_path))  # no manifest written

    assert find_installed_unreal_engines() == {}


def test_find_installed_unreal_engines_malformed_json_returns_empty_not_raises(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ProgramData", str(tmp_path))
    manifest_dir = tmp_path / "Epic" / "UnrealEngineLauncher"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "LauncherInstalled.dat").write_text("{not valid json", encoding="utf-8")

    assert find_installed_unreal_engines() == {}


def test_find_installed_unreal_engines_skips_malformed_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("ProgramData", str(tmp_path))
    _write_launcher_manifest(
        tmp_path,
        {
            "InstallationList": [
                {"InstallLocation": r"C:\UE_5.3", "AppName": "UE_5.3"},
                {"AppName": "UE_5.1"},  # missing InstallLocation
                "not a dict",
                {"InstallLocation": r"C:\Something", "AppName": None},
            ]
        },
    )

    assert find_installed_unreal_engines() == {"5.3": r"C:\UE_5.3"}


def test_find_installed_unreal_engines_unexpected_shape_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("ProgramData", str(tmp_path))
    _write_launcher_manifest(tmp_path, {"InstallationList": "not a list"})

    assert find_installed_unreal_engines() == {}


# --- find_godot_on_path -------------------------------------------------------


def test_find_godot_on_path_returns_which_result(monkeypatch):
    monkeypatch.setattr(
        "spiced.core.engine_executable_resolve.shutil.which",
        lambda name: r"C:\Godot\godot.exe" if name == "godot" else None,
    )

    assert find_godot_on_path() == r"C:\Godot\godot.exe"


def test_find_godot_on_path_falls_back_to_godot_exe(monkeypatch):
    monkeypatch.setattr(
        "spiced.core.engine_executable_resolve.shutil.which",
        lambda name: r"C:\Godot\godot.exe" if name == "godot.exe" else None,
    )

    assert find_godot_on_path() == r"C:\Godot\godot.exe"


def test_find_godot_on_path_returns_none_when_not_found(monkeypatch):
    monkeypatch.setattr("spiced.core.engine_executable_resolve.shutil.which", lambda name: None)

    assert find_godot_on_path() is None
