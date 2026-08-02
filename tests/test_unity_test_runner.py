"""Tests for the Unity Test Runner execution module.

All subprocess calls are mocked — these tests never launch a real process,
matching the rest of the suite's fully offline/local approach.
"""

from __future__ import annotations

import subprocess

import pytest

from spiced.core.unity_test_runner import (
    EDIT_MODE,
    PLAY_MODE,
    UnityEditorInfo,
    list_installed_editors,
    resolve_unity_editor,
    run_tests,
)

_PATH_2021 = r"C:\Unity\Hub\Editor\2021.3.45f1\Editor\Unity.exe"
_PATH_2022 = r"C:\Unity\Hub\Editor\2022.3.10f1\Editor\Unity.exe"
HUB_OUTPUT = f"2021.3.45f1 , installed at {_PATH_2021}\n2022.3.10f1 , installed at {_PATH_2022}\n"


class _FakeCompletedProcess:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


# --- list_installed_editors / resolve_unity_editor --------------------------


def test_list_installed_editors_parses_hub_output(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return _FakeCompletedProcess(stdout=HUB_OUTPUT)

    monkeypatch.setattr(subprocess, "run", fake_run)
    editors = list_installed_editors("fake-hub-path")
    assert editors == [
        UnityEditorInfo("2021.3.45f1", _PATH_2021),
        UnityEditorInfo("2022.3.10f1", _PATH_2022),
    ]


def test_list_installed_editors_returns_empty_on_hub_failure(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise OSError("hub not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert list_installed_editors("fake-hub-path") == []


def test_resolve_unity_editor_exact_version_match(monkeypatch):
    monkeypatch.setattr(
        "spiced.core.unity_test_runner.list_installed_editors",
        lambda hub_path, timeout_s=30: [
            UnityEditorInfo("2021.3.45f1", r"C:\Unity2021\Unity.exe"),
            UnityEditorInfo("2022.3.10f1", r"C:\Unity2022\Unity.exe"),
        ],
    )
    editor = resolve_unity_editor("2022.3.10f1", override_path=None, hub_path="fake-hub")
    assert editor == UnityEditorInfo("2022.3.10f1", r"C:\Unity2022\Unity.exe")


def test_resolve_unity_editor_no_match_returns_none(monkeypatch):
    monkeypatch.setattr(
        "spiced.core.unity_test_runner.list_installed_editors",
        lambda hub_path, timeout_s=30: [UnityEditorInfo("2021.3.45f1", r"C:\Unity2021\Unity.exe")],
    )
    assert resolve_unity_editor("2022.3.10f1", override_path=None, hub_path="fake-hub") is None


def test_resolve_unity_editor_no_hub_returns_none(monkeypatch):
    monkeypatch.setattr("spiced.core.unity_test_runner.find_unity_hub_executable", lambda: None)
    assert resolve_unity_editor("2022.3.10f1") is None


def test_resolve_unity_editor_no_required_version_returns_none():
    assert resolve_unity_editor(None) is None


def test_resolve_unity_editor_override_path_used_when_file_exists(tmp_path):
    fake_exe = tmp_path / "Unity.exe"
    fake_exe.write_text("not a real editor")
    editor = resolve_unity_editor("2022.3.10f1", override_path=str(fake_exe))
    assert editor == UnityEditorInfo("2022.3.10f1", str(fake_exe))


def test_resolve_unity_editor_override_path_missing_file_returns_none(tmp_path):
    missing = tmp_path / "does-not-exist.exe"
    assert resolve_unity_editor("2022.3.10f1", override_path=str(missing)) is None


# --- run_tests ----------------------------------------------------------------

_NUNIT_XML = (
    '<test-run total="2" passed="1" failed="1">'
    '<test-suite><test-case name="A" result="Passed"/>'
    '<test-case name="B" result="Failed"><failure><message>boom</message></failure></test-case>'
    "</test-suite></test-run>"
)


def test_run_tests_rejects_unknown_platform():
    with pytest.raises(ValueError):
        run_tests("unity.exe", "C:\\project", "Nightmare Mode")


def test_run_tests_reads_results_regardless_of_exit_code(monkeypatch):
    """Unity's exit code is not a reliable pass/fail signal, so a nonzero
    code alongside a valid results file should still be treated as success."""

    def fake_run(command, timeout, capture_output):
        results_path = command[command.index("-testResults") + 1]
        log_path = command[command.index("-logFile") + 1]
        with open(results_path, "w", encoding="utf-8") as f:
            f.write(_NUNIT_XML)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("ran fine")
        return _FakeCompletedProcess(returncode=1)  # nonzero, but tests still ran

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_tests("unity.exe", "C:\\project", EDIT_MODE)
    assert result.succeeded
    assert result.exit_code == 1
    assert "PlayerTakesDamage" not in result.results_xml  # sanity: it's our fixture XML
    assert "<test-run" in result.results_xml


def test_run_tests_no_results_file_is_reported_as_failure(monkeypatch):
    def fake_run(command, timeout, capture_output):
        log_path = command[command.index("-logFile") + 1]
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("Fatal error: could not resolve packages")
        return _FakeCompletedProcess(returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_tests("unity.exe", "C:\\project", EDIT_MODE)
    assert not result.succeeded
    assert "did not write" not in (result.error or "")  # exact wording not asserted, just presence
    assert result.error
    assert "could not resolve packages" in (result.log_tail or "")


def test_run_tests_timeout_is_reported(monkeypatch):
    def fake_run(command, timeout, capture_output):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_tests("unity.exe", "C:\\project", PLAY_MODE, timeout_s=1800)
    assert result.timed_out
    assert not result.succeeded
    assert "30 minutes" in result.error


def test_run_tests_timeout_under_a_minute_shown_in_seconds(monkeypatch):
    def fake_run(command, timeout, capture_output):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_tests("unity.exe", "C:\\project", EDIT_MODE, timeout_s=45)
    assert "45 seconds" in result.error


def test_run_tests_launch_failure_is_reported(monkeypatch):
    def fake_run(command, timeout, capture_output):
        raise OSError("not a valid Win32 application")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_tests("not-an-exe", "C:\\project", EDIT_MODE)
    assert not result.succeeded
    assert "Could not launch Unity" in result.error


def test_run_tests_result_parses_through_existing_test_result_parser(monkeypatch):
    """The whole point of reusing NUnit XML: the existing parser should read it."""
    from spiced.core.test_result_parser import parse_test_results

    def fake_run(command, timeout, capture_output):
        results_path = command[command.index("-testResults") + 1]
        with open(results_path, "w", encoding="utf-8") as f:
            f.write(_NUNIT_XML)
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_tests("unity.exe", "C:\\project", EDIT_MODE)
    parsed = parse_test_results(result.results_xml)
    assert parsed.total == 2
    assert parsed.passed == 1
    assert parsed.failed == 1
    assert "boom" in parsed.failures[0]
