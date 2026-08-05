"""Tests for core.build_pipeline: the opt-in gate + trigger orchestration.

Mocks the mechanism layer (connectors.unity_build, resolve_unity_editor) so
these tests never launch a real process or need a real Unity project.
"""

from __future__ import annotations

import pytest

from spiced.connectors import unity_build
from spiced.core import build_pipeline
from spiced.core.build_pipeline import (
    BuildNotEnabledError,
    BuildUnavailableError,
    run_build_pipeline,
    trigger_build_from_hook,
)
from spiced.core.unity_test_runner import UnityEditorInfo
from spiced.storage.build_reports import TRIGGER_COMMIT, TRIGGER_MANUAL, BuildReportRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _setup(tmp_path):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    reports = BuildReportRepository(db)
    project = projects.create("Moonlit Depths", engine="Unity")
    project = projects.set_unity_folder(
        project.id, str(tmp_path), "valid", {"unity_version": "2022.3.10f1"}
    )
    return projects, reports, project


def _patch_success(monkeypatch, output_path="C:\\proj\\Builds\\SpicedBuild.exe"):
    monkeypatch.setattr(
        build_pipeline,
        "resolve_unity_editor",
        lambda *a, **k: UnityEditorInfo("2022.3.10f1", r"C:\Unity\Unity.exe"),
    )
    monkeypatch.setattr(
        unity_build,
        "ensure_build_script",
        lambda path: unity_build.BuildScriptInfo(
            "SpicedBuildScript", "PerformBuild", str(path) + "\\Assets\\Editor\\x.cs", True
        ),
    )
    monkeypatch.setattr(
        unity_build,
        "run_build",
        lambda *a, **k: unity_build.UnityBuildResult(
            succeeded=True,
            output_path=output_path,
            log_tail="all good",
            exit_code=0,
            timed_out=False,
        ),
    )


def test_run_build_pipeline_raises_when_not_enabled(tmp_path):
    projects, reports, project = _setup(tmp_path)
    with pytest.raises(BuildNotEnabledError):
        run_build_pipeline(project, reports, trigger=TRIGGER_MANUAL)


def test_run_build_pipeline_raises_when_no_project_path(tmp_path):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    reports = BuildReportRepository(db)
    project = projects.create("No Folder")
    project = projects.set_build_pipeline_settings(project.id, True, "StandaloneWindows64")
    with pytest.raises(BuildUnavailableError):
        run_build_pipeline(project, reports, trigger=TRIGGER_MANUAL)


def test_run_build_pipeline_raises_when_editor_unresolvable(monkeypatch, tmp_path):
    projects, reports, project = _setup(tmp_path)
    project = projects.set_build_pipeline_settings(project.id, True, "StandaloneWindows64")
    monkeypatch.setattr(build_pipeline, "resolve_unity_editor", lambda *a, **k: None)
    with pytest.raises(BuildUnavailableError):
        run_build_pipeline(project, reports, trigger=TRIGGER_MANUAL)


def test_run_build_pipeline_success_saves_report(monkeypatch, tmp_path):
    projects, reports, project = _setup(tmp_path)
    project = projects.set_build_pipeline_settings(project.id, True, "StandaloneWindows64")
    _patch_success(monkeypatch)

    report = run_build_pipeline(project, reports, trigger=TRIGGER_MANUAL)
    assert report.succeeded is True
    assert report.trigger == TRIGGER_MANUAL
    assert report.target_platform == "StandaloneWindows64"
    assert report.output_path == "C:\\proj\\Builds\\SpicedBuild.exe"
    assert reports.get(report.id) == report


def test_run_build_pipeline_uses_explicit_platform_override(monkeypatch, tmp_path):
    projects, reports, project = _setup(tmp_path)
    project = projects.set_build_pipeline_settings(project.id, True, "StandaloneWindows64")
    _patch_success(monkeypatch)

    report = run_build_pipeline(
        project, reports, trigger=TRIGGER_MANUAL, target_platform="StandaloneLinux64"
    )
    assert report.target_platform == "StandaloneLinux64"


def test_run_build_pipeline_failure_still_saves_report_with_log(monkeypatch, tmp_path):
    projects, reports, project = _setup(tmp_path)
    project = projects.set_build_pipeline_settings(project.id, True, "StandaloneWindows64")
    monkeypatch.setattr(
        build_pipeline,
        "resolve_unity_editor",
        lambda *a, **k: UnityEditorInfo("2022.3.10f1", r"C:\Unity\Unity.exe"),
    )
    monkeypatch.setattr(
        unity_build,
        "ensure_build_script",
        lambda path: unity_build.BuildScriptInfo("SpicedBuildScript", "PerformBuild", "x", True),
    )
    monkeypatch.setattr(
        unity_build,
        "run_build",
        lambda *a, **k: unity_build.UnityBuildResult(
            succeeded=False,
            output_path=None,
            log_tail="Editor.log excerpt",
            exit_code=1,
            timed_out=False,
            error="No scenes are enabled in Build Settings.",
        ),
    )

    report = run_build_pipeline(project, reports, trigger=TRIGGER_MANUAL)
    assert report.succeeded is False
    assert "No scenes are enabled" in report.log_tail
    assert "Editor.log excerpt" in report.log_tail


def test_trigger_build_from_hook_delegates_to_run_build_pipeline(monkeypatch, tmp_path):
    projects, reports, project = _setup(tmp_path)
    project = projects.set_build_pipeline_settings(project.id, True, "StandaloneWindows64")
    _patch_success(monkeypatch)

    report = trigger_build_from_hook(project.id, projects, reports)
    assert report.trigger == TRIGGER_COMMIT
    assert report.succeeded is True


def test_trigger_build_from_hook_still_gated_when_not_enabled(tmp_path):
    projects, reports, project = _setup(tmp_path)
    with pytest.raises(BuildNotEnabledError):
        trigger_build_from_hook(project.id, projects, reports)


# --- Live Task Progress Transparency (Phase L): on_progress ------------------


def test_run_build_pipeline_without_on_progress_still_works(monkeypatch, tmp_path):
    """Backward compatibility: every existing caller omits ``on_progress``
    entirely -- confirms the default (None) is a true no-op, not a crash."""
    projects, reports, project = _setup(tmp_path)
    project = projects.set_build_pipeline_settings(project.id, True, "StandaloneWindows64")
    _patch_success(monkeypatch)

    report = run_build_pipeline(project, reports, trigger=TRIGGER_MANUAL)
    assert report.succeeded is True


def test_run_build_pipeline_emits_progress_for_each_real_step(monkeypatch, tmp_path):
    projects, reports, project = _setup(tmp_path)
    project = projects.set_build_pipeline_settings(project.id, True, "StandaloneWindows64")
    _patch_success(monkeypatch)

    messages: list[str] = []
    report = run_build_pipeline(
        project, reports, trigger=TRIGGER_MANUAL, on_progress=messages.append
    )
    assert report.succeeded is True
    assert len(messages) >= 4
    assert any("Editor" in m for m in messages)
    assert any("build script" in m for m in messages)
    assert any("headless" in m for m in messages)
    assert any("report" in m for m in messages)


def test_run_build_pipeline_progress_stops_before_editor_step_when_not_enabled(tmp_path):
    """A gate failure happens before the first ``on_progress`` call --
    confirms progress emission never masks an early raise."""
    projects, reports, project = _setup(tmp_path)
    messages: list[str] = []
    with pytest.raises(BuildNotEnabledError):
        run_build_pipeline(project, reports, trigger=TRIGGER_MANUAL, on_progress=messages.append)
    assert messages == []
