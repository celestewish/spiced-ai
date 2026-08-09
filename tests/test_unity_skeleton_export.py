"""Tests for connectors.unity_skeleton_export (Implementation Bible,
Feature 7). Mocks subprocess.run, same convention as the other Unity
connector tests -- no real Unity install is required."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from spiced.connectors import unity_skeleton_export as use


def test_ensure_export_script_writes_file(tmp_path):
    path = use.ensure_export_script(tmp_path)
    assert Path(path).is_file()
    assert Path(path) == tmp_path / "Assets" / "Editor" / "SpicedSkeletonExportScript.cs"
    content = Path(path).read_text(encoding="utf-8")
    assert "GetComponentsInChildren<Transform>" in content


def _fake_run_writing_result(result_data: dict):
    def _fake_run(command, timeout, capture_output):
        result_path = Path(command[command.index("-spicedResultFile") + 1])
        log_path = Path(command[command.index("-logFile") + 1])
        result_path.write_text(json.dumps(result_data), encoding="utf-8")
        log_path.write_text("log\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    return _fake_run


def test_run_export_parses_result_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        use.subprocess,
        "run",
        _fake_run_writing_result(
            {
                "run_error": None,
                "models": [
                    {
                        "model_path": "Assets/Hero.fbx",
                        "success": True,
                        "error": None,
                        "bone_names": ["Hips", "Spine", "Head"],
                    }
                ],
            }
        ),
    )

    result = use.run_export("C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/Hero.fbx"])

    assert result.error is None
    outcome = result.outcomes[0]
    assert outcome.succeeded is True
    assert outcome.bone_names == ["Hips", "Spine", "Head"]


def test_run_export_reports_per_model_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        use.subprocess,
        "run",
        _fake_run_writing_result(
            {
                "run_error": None,
                "models": [
                    {
                        "model_path": "Assets/Broken.fbx",
                        "success": False,
                        "error": "Could not load this asset as a GameObject.",
                        "bone_names": None,
                    }
                ],
            }
        ),
    )

    result = use.run_export("C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/Broken.fbx"])

    assert result.outcomes[0].succeeded is False


def test_run_export_timeout(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(use.subprocess, "run", _fake_run)

    result = use.run_export("C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/A.fbx"], timeout_s=5)

    assert result.timed_out is True


def test_run_export_unity_not_launchable(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        raise OSError("not found")

    monkeypatch.setattr(use.subprocess, "run", _fake_run)

    result = use.run_export("C:\\nonexistent\\Unity.exe", str(tmp_path), ["Assets/A.fbx"])

    assert "Could not launch Unity" in result.error


def test_run_export_uses_nographics(tmp_path, monkeypatch):
    calls = []

    def _fake_run(command, timeout, capture_output):
        calls.append(command)
        result_path = Path(command[command.index("-spicedResultFile") + 1])
        result_path.write_text(json.dumps({"run_error": None, "models": []}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(use.subprocess, "run", _fake_run)
    use.run_export("C:\\Unity\\Unity.exe", str(tmp_path), [])

    assert "-nographics" in calls[0]
