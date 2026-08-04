"""Tests for core.save_load_tester: subprocess orchestration + JSON-result
parsing (success/failure/timeout/malformed cases). All subprocess calls are
mocked — no real game executable is ever launched."""

from __future__ import annotations

import json
import subprocess

import pytest

from spiced.core.save_load_tester import (
    RESULT_PATH_ENV_VAR,
    SAVE_PATH_ENV_VAR,
    STATUS_ERROR,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_TIMED_OUT,
    NoExecutableError,
    NoSavesFolderError,
    SaveLoadTesterService,
    list_save_files,
    run_one_save,
)
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.save_integrity_reports import SaveIntegrityReportRepository


def _fake_run_writing_result(success: bool, error: str | None = None):
    def fake_run(command, env, timeout, capture_output):
        result_path = env[RESULT_PATH_ENV_VAR]
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({"success": success, "error": error}, f)
        return subprocess.CompletedProcess(command, 0)

    return fake_run


def test_run_one_save_passes_env_vars(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, env, timeout, capture_output):
        captured["env"] = env
        captured["command"] = command
        result_path = env[RESULT_PATH_ENV_VAR]
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({"success": True, "error": None}, f)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    save = tmp_path / "save1.dat"
    save.write_text("data", encoding="utf-8")

    result = run_one_save("game.exe", save)
    assert captured["command"] == ["game.exe"]
    assert captured["env"][SAVE_PATH_ENV_VAR] == str(save)
    assert result.status == STATUS_PASSED


def test_run_one_save_reads_success_result(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _fake_run_writing_result(True))
    result = run_one_save("game.exe", tmp_path / "save1.dat")
    assert result.status == STATUS_PASSED
    assert result.error is None


def test_run_one_save_reads_failure_result(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _fake_run_writing_result(False, "Inventory mismatch"))
    result = run_one_save("game.exe", tmp_path / "save1.dat")
    assert result.status == STATUS_FAILED
    assert result.error == "Inventory mismatch"


def test_run_one_save_failure_without_error_text_gets_default_message(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _fake_run_writing_result(False, None))
    result = run_one_save("game.exe", tmp_path / "save1.dat")
    assert result.status == STATUS_FAILED
    assert result.error


def test_run_one_save_missing_result_file_is_error(monkeypatch, tmp_path):
    def fake_run(command, env, timeout, capture_output):
        return subprocess.CompletedProcess(command, 0)  # never writes a result file

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_one_save("game.exe", tmp_path / "save1.dat")
    assert result.status == STATUS_ERROR
    assert "hook" in result.error.lower()


def test_run_one_save_malformed_json_is_error(monkeypatch, tmp_path):
    def fake_run(command, env, timeout, capture_output):
        result_path = env[RESULT_PATH_ENV_VAR]
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_one_save("game.exe", tmp_path / "save1.dat")
    assert result.status == STATUS_ERROR


def test_run_one_save_result_file_not_a_json_object_is_error(monkeypatch, tmp_path):
    def fake_run(command, env, timeout, capture_output):
        result_path = env[RESULT_PATH_ENV_VAR]
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(["not", "an", "object"], f)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_one_save("game.exe", tmp_path / "save1.dat")
    assert result.status == STATUS_ERROR


def test_run_one_save_timeout_is_reported(monkeypatch, tmp_path):
    def fake_run(command, env, timeout, capture_output):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_one_save("game.exe", tmp_path / "save1.dat", timeout_s=5)
    assert result.status == STATUS_TIMED_OUT


def test_run_one_save_launch_failure_is_reported(monkeypatch, tmp_path):
    def fake_run(command, env, timeout, capture_output):
        raise OSError("not a valid Win32 application")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_one_save("not-an-exe", tmp_path / "save1.dat")
    assert result.status == STATUS_ERROR
    assert "launch" in result.error.lower()


def test_list_save_files_returns_empty_for_missing_folder(tmp_path):
    assert list_save_files(tmp_path / "nope") == []


def test_list_save_files_lists_files_only(tmp_path):
    (tmp_path / "save1.dat").write_text("a", encoding="utf-8")
    (tmp_path / "save2.dat").write_text("b", encoding="utf-8")
    (tmp_path / "subfolder").mkdir()
    files = list_save_files(tmp_path)
    assert [f.name for f in files] == ["save1.dat", "save2.dat"]


# --- SaveLoadTesterService: orchestration across a folder of saves -------------


def _service_and_project(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = repo.create("Moonlit Depths")
    service = SaveLoadTesterService(SaveIntegrityReportRepository(db))
    return service, project


def test_service_run_raises_without_executable(tmp_path):
    service, project = _service_and_project(tmp_path)
    with pytest.raises(NoExecutableError):
        service.run(project, str(tmp_path / "missing.exe"), str(tmp_path))


def test_service_run_raises_without_saves(tmp_path):
    service, project = _service_and_project(tmp_path)
    exe = tmp_path / "game.exe"
    exe.write_text("fake exe", encoding="utf-8")
    empty_folder = tmp_path / "saves"
    empty_folder.mkdir()
    with pytest.raises(NoSavesFolderError):
        service.run(project, str(exe), str(empty_folder))


def test_service_run_saves_a_report_with_rollup_counts(monkeypatch, tmp_path):
    service, project = _service_and_project(tmp_path)
    exe = tmp_path / "game.exe"
    exe.write_text("fake exe", encoding="utf-8")
    saves = tmp_path / "saves"
    saves.mkdir()
    (saves / "save1.dat").write_text("a", encoding="utf-8")
    (saves / "save2.dat").write_text("b", encoding="utf-8")

    call_count = {"n": 0}

    def fake_run(command, env, timeout, capture_output):
        call_count["n"] += 1
        result_path = env[RESULT_PATH_ENV_VAR]
        success = call_count["n"] == 1  # first save passes, second fails
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({"success": success, "error": None if success else "boom"}, f)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    run = service.run(project, str(exe), str(saves))

    assert run.passed_count == 1
    assert run.failed_count == 1
    assert run.report is not None
    assert run.report.passed_count == 1
    assert run.report.failed_count == 1
    assert len(run.report.results) == 2
    assert service.history(project.id)[0].id == run.report.id
