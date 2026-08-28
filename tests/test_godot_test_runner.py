"""Tests for connectors.godot_test_runner.

Same fake-``subprocess.run`` pattern as ``tests/test_unity_build.py`` and
``tests/test_godot_build.py``.
"""

from __future__ import annotations

import subprocess

from spiced.connectors.godot_test_runner import is_gut_installed, run_gut_tests

_JUNIT_SAMPLE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<testsuites><testsuite name="test_player" tests="1" failures="0">'
    '<testcase name="test_start_sets_position"/>'
    "</testsuite></testsuites>"
)


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _install_gut(project_path):
    addon_dir = project_path / "addons" / "gut"
    addon_dir.mkdir(parents=True)
    (addon_dir / "plugin.cfg").write_text(
        '[plugin]\nname="Gut"\nscript="gut_plugin.gd"\n', encoding="utf-8"
    )
    (addon_dir / "gut_cmdln.gd").write_text("extends SceneTree\n", encoding="utf-8")


def test_is_gut_installed_false_when_no_addons_folder(tmp_path):
    assert is_gut_installed(tmp_path) is False


def test_is_gut_installed_false_for_unrelated_addon_named_gut(tmp_path):
    addon_dir = tmp_path / "addons" / "gut"
    addon_dir.mkdir(parents=True)
    (addon_dir / "plugin.cfg").write_text('[plugin]\nname="Not Gut"\n', encoding="utf-8")
    # No gut_cmdln.gd -- not actually GUT.

    assert is_gut_installed(tmp_path) is False


def test_is_gut_installed_true_when_properly_installed(tmp_path):
    _install_gut(tmp_path)
    assert is_gut_installed(tmp_path) is True


def test_run_gut_tests_reads_results_regardless_of_exit_code(monkeypatch, tmp_path):
    _install_gut(tmp_path)

    def fake_run(command, timeout, capture_output, text, errors):
        result_path = _extract_flag_value(command, "-gjunit_xml_file=")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(_JUNIT_SAMPLE)
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_gut_tests("godot", str(tmp_path))

    assert result.succeeded is True
    assert "test_start_sets_position" in result.results_xml


def test_run_gut_tests_no_results_file_is_reported_as_failure(monkeypatch, tmp_path):
    _install_gut(tmp_path)

    def fake_run(command, timeout, capture_output, text, errors):
        return _FakeCompletedProcess(returncode=1, stderr="Fatal parse error")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_gut_tests("godot", str(tmp_path))

    assert result.succeeded is False
    assert "Fatal parse error" in (result.log_tail or "")


def test_run_gut_tests_timeout_is_reported(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_gut_tests("godot", str(tmp_path), timeout_s=60)

    assert result.timed_out is True
    assert result.succeeded is False


def test_run_gut_tests_launch_failure_is_reported(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        raise OSError("not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_gut_tests("not-godot", str(tmp_path))

    assert result.succeeded is False
    assert "Could not launch Godot" in result.error


def test_run_gut_tests_command_includes_gdir_and_gexit(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, timeout, capture_output, text, errors):
        captured["command"] = command
        result_path = _extract_flag_value(command, "-gjunit_xml_file=")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(_JUNIT_SAMPLE)
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_gut_tests("godot", str(tmp_path), test_dir="res://test")

    command = captured["command"]
    assert "-gdir=res://test" in command
    assert "-gexit" in command
    assert "-s" in command


def _extract_flag_value(command: list[str], prefix: str) -> str:
    for arg in command:
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    raise AssertionError(f"{prefix} not found in command: {command}")
