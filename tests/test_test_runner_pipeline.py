"""Tests for core.test_runner_pipeline: the engine-dispatching entry point
that replaces the UI's old direct call into connectors.unity_test_runner.

Mocks the connector layer (godot_test_runner, unreal_test_runner,
unity_test_runner.run_tests) so these tests never launch a real process.
"""

from __future__ import annotations

import json

import pytest

from spiced.connectors import godot_test_runner, unreal_test_runner
from spiced.core import test_runner_pipeline
from spiced.core.test_runner_pipeline import TestRunnerNotAvailableError, run_test_pipeline
from spiced.core.testing import SOURCE_GODOT_RUN, SOURCE_UNITY_RUN, SOURCE_UNREAL_RUN
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _project(tmp_path, engine: str):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Fixture Game", engine=engine)
    return projects.set_unity_folder(project.id, str(tmp_path), "valid")


# --- Unity (unchanged behavior, extracted from the old worker) -------------


def test_run_test_pipeline_dispatches_to_unity(monkeypatch, tmp_path):
    project = _project(tmp_path, "Unity")
    monkeypatch.setattr(
        test_runner_pipeline,
        "run_unity_tests",
        lambda *a, **k: type(
            "R", (), {"succeeded": True, "results_xml": "<xml/>", "error": None, "log_tail": None}
        )(),
    )

    result = run_test_pipeline(project, "/path/to/Unity.exe", "EditMode")

    assert result.succeeded is True
    assert result.raw_text == "<xml/>"
    assert result.source_type == SOURCE_UNITY_RUN
    assert result.source_filename == "unity-editmode-run.xml"


# --- Godot -------------------------------------------------------------


def test_run_test_pipeline_godot_raises_without_gut_installed(tmp_path):
    project = _project(tmp_path, "Godot")
    with pytest.raises(TestRunnerNotAvailableError):
        run_test_pipeline(project, "/usr/bin/godot", "")


def test_run_test_pipeline_dispatches_to_godot_and_adapts_junit(monkeypatch, tmp_path):
    project = _project(tmp_path, "Godot")
    monkeypatch.setattr(godot_test_runner, "is_gut_installed", lambda path: True)
    monkeypatch.setattr(
        godot_test_runner,
        "run_gut_tests",
        lambda *a, **k: godot_test_runner.GodotTestRunResult(
            results_xml=(
                '<testsuites><testsuite><testcase classname="T" name="ok" />'
                "</testsuite></testsuites>"
            ),
            log_tail="all good",
            timed_out=False,
            exit_code=0,
        ),
    )

    result = run_test_pipeline(project, "/usr/bin/godot", "")

    assert result.succeeded is True
    assert result.source_type == SOURCE_GODOT_RUN
    data = json.loads(result.raw_text)
    assert data["tests"][0]["status"] == "passed"


def test_run_test_pipeline_godot_failed_run_has_no_raw_text(monkeypatch, tmp_path):
    project = _project(tmp_path, "Godot")
    monkeypatch.setattr(godot_test_runner, "is_gut_installed", lambda path: True)
    monkeypatch.setattr(
        godot_test_runner,
        "run_gut_tests",
        lambda *a, **k: godot_test_runner.GodotTestRunResult(
            results_xml=None,
            log_tail="crashed before tests ran",
            timed_out=False,
            exit_code=1,
            error="Godot exited without writing a GUT results file.",
        ),
    )

    result = run_test_pipeline(project, "/usr/bin/godot", "")

    assert result.succeeded is False
    assert result.raw_text is None
    assert "GUT results file" in result.error


# --- Unreal -------------------------------------------------------------


def test_run_test_pipeline_unreal_raises_without_uproject(tmp_path):
    project = _project(tmp_path, "Unreal")  # no .uproject file written
    with pytest.raises(TestRunnerNotAvailableError):
        run_test_pipeline(project, r"C:\UE\UnrealEditor-Cmd.exe", "")


def test_run_test_pipeline_dispatches_to_unreal_and_adapts_report(monkeypatch, tmp_path):
    (tmp_path / "FixtureGame.uproject").write_text("{}", encoding="utf-8")
    project = _project(tmp_path, "Unreal")
    monkeypatch.setattr(
        unreal_test_runner,
        "run_automation_tests",
        lambda *a, **k: unreal_test_runner.UnrealTestRunResult(
            report_json=json.dumps({"succeeded": 4, "failed": 1}),
            log_tail="ran ok",
            timed_out=False,
            exit_code=0,
        ),
    )

    result = run_test_pipeline(project, r"C:\UE\UnrealEditor-Cmd.exe", "")

    assert result.succeeded is True
    assert result.source_type == SOURCE_UNREAL_RUN
    data = json.loads(result.raw_text)
    assert data == {"passed": 4, "failed": 1, "skipped": 0, "total": 5}
