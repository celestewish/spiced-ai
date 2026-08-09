"""Tests for connectors.unity_shader_variant_export (Implementation Bible,
Feature 6). Mocks subprocess.run, the same convention as
test_unity_asset_export.py / test_unity_visual_capture.py -- no real Unity
install is required."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from spiced.connectors import unity_shader_variant_export as usve


def test_ensure_export_script_writes_file(tmp_path):
    path = usve.ensure_export_script(tmp_path)
    assert Path(path).is_file()
    assert Path(path) == tmp_path / "Assets" / "Editor" / "SpicedShaderVariantExportScript.cs"
    content = Path(path).read_text(encoding="utf-8")
    assert "ShaderUtil.GetVariantCount" in content


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
        usve.subprocess,
        "run",
        _fake_run_writing_result(
            {
                "run_error": None,
                "shaders": [
                    {
                        "shader_path": "Assets/Shaders/Toon.shader",
                        "success": True,
                        "error": None,
                        "variant_count": 256,
                        "pass_count": 2,
                    }
                ],
            }
        ),
    )

    result = usve.run_export(
        "C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/Shaders/Toon.shader"]
    )

    assert result.error is None
    outcome = result.outcomes[0]
    assert outcome.succeeded is True
    assert outcome.variant_count == 256
    assert outcome.pass_count == 2


def test_run_export_reports_per_shader_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        usve.subprocess,
        "run",
        _fake_run_writing_result(
            {
                "run_error": None,
                "shaders": [
                    {
                        "shader_path": "Assets/Shaders/Broken.shader",
                        "success": False,
                        "error": "Could not load this asset as a Shader.",
                        "variant_count": None,
                        "pass_count": None,
                    }
                ],
            }
        ),
    )

    result = usve.run_export(
        "C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/Shaders/Broken.shader"]
    )

    assert result.outcomes[0].succeeded is False
    assert "Shader" in result.outcomes[0].error


def test_run_export_no_result_file_is_a_run_error(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(usve.subprocess, "run", _fake_run)

    result = usve.run_export("C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/A.shader"])

    assert result.error is not None
    assert "exited without writing" in result.error


def test_run_export_timeout(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(usve.subprocess, "run", _fake_run)

    result = usve.run_export(
        "C:\\Unity\\Unity.exe", str(tmp_path), ["Assets/A.shader"], timeout_s=5
    )

    assert result.timed_out is True
    assert result.error is not None


def test_run_export_unity_not_launchable(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        raise OSError("not found")

    monkeypatch.setattr(usve.subprocess, "run", _fake_run)

    result = usve.run_export("C:\\nonexistent\\Unity.exe", str(tmp_path), ["Assets/A.shader"])

    assert "Could not launch Unity" in result.error


def test_run_export_uses_nographics(tmp_path, monkeypatch):
    calls = []

    def _fake_run(command, timeout, capture_output):
        calls.append(command)
        result_path = Path(command[command.index("-spicedResultFile") + 1])
        result_path.write_text(json.dumps({"run_error": None, "shaders": []}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(usve.subprocess, "run", _fake_run)
    usve.run_export("C:\\Unity\\Unity.exe", str(tmp_path), [])

    assert "-nographics" in calls[0]
