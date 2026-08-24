"""Tests for connectors.unreal_build.

Same fake-``subprocess.run`` pattern as ``tests/test_unity_build.py`` and
``tests/test_godot_build.py``.
"""

from __future__ import annotations

import subprocess

from spiced.connectors.unreal_build import run_build


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_build_succeeds_when_exit_code_zero_and_archive_populated(monkeypatch, tmp_path):
    archive_dir = tmp_path / "Archive"
    archive_dir.mkdir()

    def fake_run(command, timeout, capture_output, text, errors):
        (archive_dir / "WindowsNoEditor").mkdir()
        return _FakeCompletedProcess(returncode=0, stdout="BUILD SUCCESSFUL")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_build("RunUAT.bat", str(tmp_path / "TPS.uproject"), "Win64", str(archive_dir))

    assert result.succeeded is True
    assert result.output_path == str(archive_dir)
    assert result.error is None


def test_run_build_fails_on_nonzero_exit_code(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        return _FakeCompletedProcess(returncode=1, stderr="BUILD FAILED")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_build(
        "RunUAT.bat", str(tmp_path / "TPS.uproject"), "Win64", str(tmp_path / "Archive")
    )

    assert result.succeeded is False
    assert "BUILD FAILED" in (result.log_tail or "")


def test_run_build_fails_when_archive_directory_empty_despite_zero_exit_code(
    monkeypatch, tmp_path
):
    archive_dir = tmp_path / "Archive"
    archive_dir.mkdir()

    def fake_run(command, timeout, capture_output, text, errors):
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_build("RunUAT.bat", str(tmp_path / "TPS.uproject"), "Win64", str(archive_dir))

    assert result.succeeded is False
    assert "empty" in result.error


def test_run_build_timeout_is_reported(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_build(
        "RunUAT.bat",
        str(tmp_path / "TPS.uproject"),
        "Win64",
        str(tmp_path / "Archive"),
        timeout_s=60,
    )

    assert result.timed_out is True
    assert result.succeeded is False


def test_run_build_launch_failure_is_reported(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        raise OSError("not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_build(
        "not-runuat", str(tmp_path / "TPS.uproject"), "Win64", str(tmp_path / "Archive")
    )

    assert result.succeeded is False
    assert "Could not launch RunUAT" in result.error


def test_run_build_command_shape(monkeypatch, tmp_path):
    captured = {}
    archive_dir = tmp_path / "Archive"
    archive_dir.mkdir()

    def fake_run(command, timeout, capture_output, text, errors):
        captured["command"] = command
        (archive_dir / "out").mkdir()
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    uproject = str(tmp_path / "TPS.uproject")
    run_build("RunUAT.bat", uproject, "Win64", str(archive_dir), client_config="Shipping")

    command = captured["command"]
    assert command[0] == "RunUAT.bat"
    assert command[1] == "BuildCookRun"
    assert f"-project={uproject}" in command
    assert "-platform=Win64" in command
    assert "-clientconfig=Shipping" in command
    assert f"-archivedirectory={archive_dir}" in command
