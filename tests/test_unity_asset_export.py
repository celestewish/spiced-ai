"""Tests for connectors.unity_asset_export: the headless Unity mesh-pivot
export mechanism (Implementation Bible, Feature 3). Mocks subprocess.run,
the same convention as test_unity_visual_capture.py / test_build_pipeline.py
-- no real Unity install is required or assumed."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from spiced.connectors import unity_asset_export as uae


def test_ensure_export_script_writes_file(tmp_path):
    path = uae.ensure_export_script(tmp_path)
    assert Path(path).is_file()
    assert Path(path) == tmp_path / "Assets" / "Editor" / "SpicedAssetExportScript.cs"
    content = Path(path).read_text(encoding="utf-8")
    assert "SpicedAssetExportScript" in content
    assert "PerformExport" in content


def _fake_run_writing_result(result_data: dict, log_text: str = "log line\n"):
    def _fake_run(command, timeout, capture_output):
        result_path = Path(command[command.index("-spicedResultFile") + 1])
        log_path = Path(command[command.index("-logFile") + 1])
        result_path.write_text(json.dumps(result_data), encoding="utf-8")
        log_path.write_text(log_text, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    return _fake_run


def test_run_export_parses_result_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        uae.subprocess,
        "run",
        _fake_run_writing_result(
            {
                "run_error": None,
                "assets": [
                    {
                        "asset_path": "Assets/Models/Chair.fbx",
                        "success": True,
                        "error": None,
                        "pivot_offset": 0.05,
                        "bounds_size": 1.0,
                    }
                ],
            }
        ),
    )

    result = uae.run_export(
        "C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/Models/Chair.fbx"]
    )

    assert result.error is None
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.succeeded is True
    assert outcome.pivot_offset == 0.05
    assert outcome.bounds_size == 1.0


def test_run_export_reports_per_asset_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        uae.subprocess,
        "run",
        _fake_run_writing_result(
            {
                "run_error": None,
                "assets": [
                    {
                        "asset_path": "Assets/Models/Broken.fbx",
                        "success": False,
                        "error": "Could not load this asset as a GameObject or Mesh.",
                        "pivot_offset": None,
                        "bounds_size": None,
                    }
                ],
            }
        ),
    )

    result = uae.run_export(
        "C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/Models/Broken.fbx"]
    )

    assert result.outcomes[0].succeeded is False
    assert "GameObject or Mesh" in result.outcomes[0].error


def test_run_export_no_result_file_is_a_run_error(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(uae.subprocess, "run", _fake_run)

    result = uae.run_export("C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/Models/A.fbx"])

    assert result.error is not None
    assert "exited without writing" in result.error


def test_run_export_timeout(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(uae.subprocess, "run", _fake_run)

    result = uae.run_export(
        "C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/Models/A.fbx"], timeout_s=5
    )

    assert result.timed_out is True
    assert result.error is not None


def test_run_export_unity_not_launchable(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        raise OSError("not found")

    monkeypatch.setattr(uae.subprocess, "run", _fake_run)

    result = uae.run_export(
        "C:\\nonexistent\\Unity.exe", str(tmp_path), ["Assets/Models/A.fbx"]
    )

    assert "Could not launch Unity" in result.error


def test_run_export_uses_nographics(tmp_path, monkeypatch):
    calls = []

    def _fake_run(command, timeout, capture_output):
        calls.append(command)
        result_path = Path(command[command.index("-spicedResultFile") + 1])
        result_path.write_text(json.dumps({"run_error": None, "assets": []}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(uae.subprocess, "run", _fake_run)
    uae.run_export("C:\\Unity\\Unity.exe", str(tmp_path), [])

    assert "-nographics" in calls[0]  # no rendering needed, unlike unity_visual_capture
