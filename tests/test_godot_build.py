"""Tests for connectors.godot_build.

Unlike the other Godot connector tests, no real ``export_presets.cfg`` was
available to fetch (see the module's docstring on why -- it's a locally
generated, conventionally gitignored file). The preset-name parsing tests
below use Godot's documented ``[preset.N]``/ConfigFile-style shape, and the
subprocess-driving tests use the same fake-``subprocess.run`` pattern as
``tests/test_unity_build.py``.
"""

from __future__ import annotations

import subprocess

from spiced.connectors.godot_build import (
    export_presets_path,
    list_export_presets,
    run_export,
)

EXPORT_PRESETS_CFG_TEXT = """[preset.0]

name="Windows Desktop"
platform="Windows Desktop"
runnable=true
export_filter="all_resources"

[preset.0.options]

custom_template/debug=""
custom_template/release=""

[preset.1]

name="Linux"
platform="Linux"
runnable=true
"""


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_list_export_presets_empty_when_no_file(tmp_path):
    assert list_export_presets(tmp_path) == []


def test_list_export_presets_parses_names_and_platforms(tmp_path):
    export_presets_path(tmp_path).write_text(EXPORT_PRESETS_CFG_TEXT, encoding="utf-8")

    presets = list_export_presets(tmp_path)

    assert [(p.index, p.name, p.platform) for p in presets] == [
        (0, "Windows Desktop", "Windows Desktop"),
        (1, "Linux", "Linux"),
    ]


def test_run_export_succeeds_when_exit_code_zero_and_output_exists(monkeypatch, tmp_path):
    output = tmp_path / "build" / "game.exe"
    output.parent.mkdir()

    def fake_run(command, timeout, capture_output, text, errors):
        output.write_bytes(b"\x00")
        return _FakeCompletedProcess(returncode=0, stdout="Exported successfully.")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_export("godot", str(tmp_path), "Windows Desktop", str(output))

    assert result.succeeded is True
    assert result.output_path == str(output)
    assert result.error is None


def test_run_export_fails_on_nonzero_exit_code(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        return _FakeCompletedProcess(returncode=1, stderr="ERROR: export preset not found.")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_export("godot", str(tmp_path), "Nonexistent", str(tmp_path / "out.exe"))

    assert result.succeeded is False
    assert "ERROR: export preset not found." in (result.log_tail or "")


def test_run_export_fails_when_output_missing_despite_zero_exit_code(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_export("godot", str(tmp_path), "Windows Desktop", str(tmp_path / "out.exe"))

    assert result.succeeded is False
    assert "wasn't found" in result.error


def test_run_export_timeout_is_reported(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_export(
        "godot", str(tmp_path), "Windows Desktop", str(tmp_path / "out.exe"), timeout_s=60
    )

    assert result.timed_out is True
    assert result.succeeded is False


def test_run_export_launch_failure_is_reported(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output, text, errors):
        raise OSError("not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_export("not-godot", str(tmp_path), "Windows Desktop", str(tmp_path / "out.exe"))

    assert result.succeeded is False
    assert "Could not launch Godot" in result.error


def test_run_export_command_shape(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, timeout, capture_output, text, errors):
        captured["command"] = command
        (tmp_path / "out.exe").write_bytes(b"\x00")
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_export("godot", str(tmp_path), "Windows Desktop", str(tmp_path / "out.exe"))

    command = captured["command"]
    assert command[0] == "godot"
    assert "--headless" in command
    assert "--export-release" in command
    idx = command.index("--export-release")
    assert command[idx + 1] == "Windows Desktop"
    assert command[idx + 2] == str(tmp_path / "out.exe")
