"""Tests for connectors.unreal_test_runner.

Same fake-``subprocess.run`` pattern as ``tests/test_unity_build.py``,
``tests/test_godot_build.py``, and ``tests/test_godot_test_runner.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from spiced.connectors.unreal_test_runner import run_automation_tests

_REPORT_JSON_SAMPLE = '{"tests": [{"testName": "BatteryTests", "state": "Success"}]}'


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _extract_flag_value(command: list[str], prefix: str) -> str:
    for arg in command:
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    raise AssertionError(f"{prefix} not found in command: {command}")


def test_run_automation_tests_reads_report_regardless_of_exit_code(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        report_dir = _extract_flag_value(command, "-ReportOutputPath=")
        report_path = Path(report_dir)
        report_path.mkdir(parents=True, exist_ok=True)
        (report_path / "index.json").write_text(_REPORT_JSON_SAMPLE, encoding="utf-8")
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_automation_tests("UnrealEditor-Cmd.exe", str(tmp_path / "TPS.uproject"))

    assert result.succeeded is True
    assert "BatteryTests" in result.report_json


def test_run_automation_tests_no_report_is_reported_as_failure(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        return _FakeCompletedProcess(returncode=1, stderr="Fatal error: could not load project")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_automation_tests("UnrealEditor-Cmd.exe", str(tmp_path / "TPS.uproject"))

    assert result.succeeded is False
    assert "Fatal error" in (result.log_tail or "")


def test_run_automation_tests_timeout_is_reported(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_automation_tests(
        "UnrealEditor-Cmd.exe", str(tmp_path / "TPS.uproject"), timeout_s=60
    )

    assert result.timed_out is True
    assert result.succeeded is False


def test_run_automation_tests_launch_failure_is_reported(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        raise OSError("not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_automation_tests("not-unreal", str(tmp_path / "TPS.uproject"))

    assert result.succeeded is False
    assert "Could not launch UnrealEditor-Cmd" in result.error


def test_run_automation_tests_command_includes_filter_and_report_path(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, timeout, capture_output, text, errors):
        captured["command"] = command
        report_dir = _extract_flag_value(command, "-ReportOutputPath=")
        report_path = Path(report_dir)
        report_path.mkdir(parents=True, exist_ok=True)
        (report_path / "index.json").write_text(_REPORT_JSON_SAMPLE, encoding="utf-8")
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_automation_tests(
        "UnrealEditor-Cmd.exe", str(tmp_path / "TPS.uproject"), test_filter="TPS.Battery"
    )

    command = captured["command"]
    exec_cmds_arg = next(arg for arg in command if arg.startswith("-ExecCmds="))
    assert "TPS.Battery" in exec_cmds_arg
    assert "-unattended" in command
    assert any(arg.startswith("-ReportOutputPath=") for arg in command)


def test_run_automation_tests_defaults_to_wildcard_filter(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, timeout, capture_output, text, errors):
        captured["command"] = command
        report_dir = _extract_flag_value(command, "-ReportOutputPath=")
        report_path = Path(report_dir)
        report_path.mkdir(parents=True, exist_ok=True)
        (report_path / "index.json").write_text(_REPORT_JSON_SAMPLE, encoding="utf-8")
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_automation_tests("UnrealEditor-Cmd.exe", str(tmp_path / "TPS.uproject"))

    exec_cmds_arg = next(arg for arg in captured["command"] if arg.startswith("-ExecCmds="))
    assert "Automation RunTests *;Quit" in exec_cmds_arg
