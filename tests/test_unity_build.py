"""Tests for the Automated Build Pipeline mechanism module.

All subprocess calls are mocked — these tests never launch a real process and
never require a real Unity project, matching test_unity_test_runner.py's
fully offline/local approach.
"""

from __future__ import annotations

import json
import subprocess

from spiced.connectors.unity_build import (
    BuildScriptInfo,
    ensure_build_script,
    find_existing_build_script,
    run_build,
)

# --- find_existing_build_script / ensure_build_script ------------------------


def test_find_existing_build_script_returns_none_when_no_editor_folder(tmp_path):
    assert find_existing_build_script(tmp_path) is None


def test_find_existing_build_script_returns_none_when_no_matching_script(tmp_path):
    editor_dir = tmp_path / "Assets" / "Editor"
    editor_dir.mkdir(parents=True)
    (editor_dir / "Unrelated.cs").write_text("public class Unrelated {}", encoding="utf-8")
    assert find_existing_build_script(tmp_path) is None


def test_find_existing_build_script_detects_a_hand_written_script(tmp_path):
    editor_dir = tmp_path / "Assets" / "Editor"
    editor_dir.mkdir(parents=True)
    (editor_dir / "MyBuilder.cs").write_text(
        "public class MyBuilder {\n"
        "    public static void Build() {\n"
        "        BuildPipeline.BuildPlayer(null, \"out\", BuildTarget.StandaloneWindows64, "
        "BuildOptions.None);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    info = find_existing_build_script(tmp_path)
    assert info is not None
    assert info.class_name == "MyBuilder"
    assert info.method_name == "Build"
    assert info.execute_method == "MyBuilder.Build"
    assert info.generated is False


def test_ensure_build_script_writes_a_new_script_when_none_found(tmp_path):
    info = ensure_build_script(tmp_path)
    assert info.generated is True
    assert info.execute_method == "SpicedBuildScript.PerformBuild"
    script_path = tmp_path / "Assets" / "Editor" / "SpicedBuildScript.cs"
    assert script_path.is_file()
    text = script_path.read_text(encoding="utf-8")
    assert "BuildPipeline.BuildPlayer" in text
    assert "Spiced" in text  # clearly labeled as Spiced-generated


def test_ensure_build_script_reuses_an_existing_script_without_overwriting(tmp_path):
    editor_dir = tmp_path / "Assets" / "Editor"
    editor_dir.mkdir(parents=True)
    existing = editor_dir / "MyBuilder.cs"
    existing.write_text(
        "public class MyBuilder {\n"
        "    public static void Go() { BuildPipeline.BuildPlayer(null, \"o\", "
        "BuildTarget.StandaloneWindows64, BuildOptions.None); }\n"
        "}\n",
        encoding="utf-8",
    )
    info = ensure_build_script(tmp_path)
    assert info == BuildScriptInfo("MyBuilder", "Go", str(existing), generated=False)
    # No SpicedBuildScript.cs should have been written alongside it.
    assert not (editor_dir / "SpicedBuildScript.cs").exists()


def test_ensure_build_script_creates_editor_folder_if_missing(tmp_path):
    assert not (tmp_path / "Assets" / "Editor").exists()
    ensure_build_script(tmp_path)
    assert (tmp_path / "Assets" / "Editor").is_dir()


# --- run_build -----------------------------------------------------------------


def _fake_run_writing_result(success: bool, error: str | None = None, output_path=None):
    def fake_run(command, timeout, capture_output):
        log_path = command[command.index("-logFile") + 1]
        result_path = command[command.index("-spicedResultFile") + 1]
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("Unity build log output")
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({"success": success, "error": error, "output_path": output_path}, f)
        return _FakeCompletedProcess(returncode=0 if success else 1)

    return fake_run


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def test_run_build_reads_success_result_regardless_of_exit_code(monkeypatch, tmp_path):
    output = str(tmp_path / "Builds" / "SpicedBuild.exe")
    monkeypatch.setattr(
        subprocess, "run", _fake_run_writing_result(True, None, output)
    )
    result = run_build(
        "unity.exe", str(tmp_path), "StandaloneWindows64", str(tmp_path / "Builds"),
        "SpicedBuildScript.PerformBuild",
    )
    assert result.succeeded
    assert result.output_path == output
    assert result.error is None


def test_run_build_reads_failure_result(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run", _fake_run_writing_result(False, "No scenes are enabled.")
    )
    result = run_build(
        "unity.exe", str(tmp_path), "StandaloneWindows64", str(tmp_path / "Builds"),
        "SpicedBuildScript.PerformBuild",
    )
    assert not result.succeeded
    assert result.error == "No scenes are enabled."


def test_run_build_no_result_file_is_reported_as_failure(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output):
        log_path = command[command.index("-logFile") + 1]
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("Fatal error before build could start")
        return _FakeCompletedProcess(returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_build(
        "unity.exe", str(tmp_path), "StandaloneWindows64", str(tmp_path / "Builds"),
        "SpicedBuildScript.PerformBuild",
    )
    assert not result.succeeded
    assert result.error
    assert "Fatal error" in (result.log_tail or "")


def test_run_build_timeout_is_reported(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_build(
        "unity.exe", str(tmp_path), "StandaloneWindows64", str(tmp_path / "Builds"),
        "SpicedBuildScript.PerformBuild", timeout_s=60,
    )
    assert result.timed_out
    assert not result.succeeded


def test_run_build_launch_failure_is_reported(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output):
        raise OSError("not a valid Win32 application")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_build(
        "not-an-exe", str(tmp_path), "StandaloneWindows64", str(tmp_path / "Builds"),
        "SpicedBuildScript.PerformBuild",
    )
    assert not result.succeeded
    assert "Could not launch Unity" in result.error


def test_run_build_command_includes_execute_method_and_target(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, timeout, capture_output):
        captured["command"] = command
        result_path = command[command.index("-spicedResultFile") + 1]
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({"success": True, "error": None, "output_path": None}, f)
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_build(
        "unity.exe", str(tmp_path), "StandaloneOSX", str(tmp_path / "Builds"),
        "MyBuilder.Go",
    )
    command = captured["command"]
    assert "-executeMethod" in command
    assert command[command.index("-executeMethod") + 1] == "MyBuilder.Go"
    assert command[command.index("-buildTarget") + 1] == "StandaloneOSX"
    assert "-batchmode" in command
    assert "-nographics" in command
