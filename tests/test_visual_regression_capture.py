"""Tests for automation.visual_regression_capture (Implementation Bible,
Feature 2). The capture step (``connectors.unity_visual_capture.run_capture``)
is monkeypatched -- no real Unity install is required -- but the pixel-diff
step runs for real against small Pillow-generated PNGs, exercising the
actual reused core.visual_regression diff math end to end."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from spiced.automation import visual_regression_capture as vrc
from spiced.automation.finding import STATUS_ERROR, STATUS_FLAGGED, STATUS_PASS
from spiced.connectors.unity_visual_capture import CaptureRunResult, SceneCaptureOutcome
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.visual_regression_captures import VisualRegressionCaptureRepository
from spiced.storage.visual_regression_key_scenes import VisualRegressionKeySceneRepository


def _solid_png(path, color):
    Image.new("RGB", (40, 40), color=color).save(path)


SCENES = [
    vrc.KeyScene(
        scene_path="Assets/Scenes/Main.unity", label="Main Hall", marker_name="Cap_MainHall"
    )
]


# --- capture_key_scenes ---------------------------------------------------


def test_capture_key_scenes_names_files_by_slugged_label(tmp_path, monkeypatch):
    captured_requests = []

    def fake_run_capture(unity_path, project_path, requests, timeout_s=600):
        captured_requests.extend(requests)
        return CaptureRunResult(
            outcomes=[
                SceneCaptureOutcome(
                    scene_path=r.scene_path, output_path=r.output_path, succeeded=True
                )
                for r in requests
            ]
        )

    monkeypatch.setattr(vrc, "run_capture", fake_run_capture)
    out_dir = tmp_path / "run1"

    vrc.capture_key_scenes("Unity.exe", str(tmp_path), SCENES, out_dir)

    assert captured_requests[0].output_path == str(out_dir / "Main_Hall.png")
    assert out_dir.is_dir()


# --- compare_captures -------------------------------------------------------


def test_compare_captures_no_previous_dir_is_info(tmp_path):
    current = tmp_path / "Main_Hall.png"
    _solid_png(current, (10, 10, 10))
    capture_result = CaptureRunResult(
        outcomes=[
            SceneCaptureOutcome(
                scene_path=SCENES[0].scene_path, output_path=str(current), succeeded=True
            )
        ]
    )

    finding = vrc.compare_captures(SCENES, capture_result, None, project_id="1")

    assert finding.status == STATUS_PASS
    assert finding.items[0].severity == "info"
    assert "no previous build" in finding.items[0].message


def test_compare_captures_unchanged_scene_is_info(tmp_path):
    prev_dir = tmp_path / "prev"
    prev_dir.mkdir()
    cur_dir = tmp_path / "cur"
    cur_dir.mkdir()
    _solid_png(prev_dir / "Main_Hall.png", (20, 30, 40))
    _solid_png(cur_dir / "Main_Hall.png", (20, 30, 40))

    capture_result = CaptureRunResult(
        outcomes=[
            SceneCaptureOutcome(
                scene_path=SCENES[0].scene_path,
                output_path=str(cur_dir / "Main_Hall.png"),
                succeeded=True,
            )
        ]
    )

    finding = vrc.compare_captures(SCENES, capture_result, prev_dir, project_id="1")

    assert finding.status == STATUS_PASS
    assert finding.items[0].severity == "info"
    assert finding.items[0].detail["percent_changed"] == 0.0


def test_compare_captures_changed_scene_is_flagged_with_diff_image(tmp_path):
    prev_dir = tmp_path / "prev"
    prev_dir.mkdir()
    cur_dir = tmp_path / "cur"
    cur_dir.mkdir()
    diff_dir = tmp_path / "diffs"
    _solid_png(prev_dir / "Main_Hall.png", (0, 0, 0))
    _solid_png(cur_dir / "Main_Hall.png", (255, 255, 255))  # wildly different -> flagged

    capture_result = CaptureRunResult(
        outcomes=[
            SceneCaptureOutcome(
                scene_path=SCENES[0].scene_path,
                output_path=str(cur_dir / "Main_Hall.png"),
                succeeded=True,
            )
        ]
    )

    finding = vrc.compare_captures(
        SCENES, capture_result, prev_dir, project_id="1", diff_output_dir=diff_dir
    )

    assert finding.status == STATUS_FLAGGED
    item = finding.items[0]
    assert item.severity == "warning"
    assert item.detail["percent_changed"] == 100.0
    assert item.detail["diff_image"] is not None
    assert (diff_dir / "diff_Main_Hall.png").is_file()


def test_compare_captures_scene_capture_failure_is_error(tmp_path):
    capture_result = CaptureRunResult(
        outcomes=[
            SceneCaptureOutcome(
                scene_path=SCENES[0].scene_path,
                output_path=str(tmp_path / "Main_Hall.png"),
                succeeded=False,
                error="No GameObject named 'Cap_MainHall' found",
            )
        ]
    )

    finding = vrc.compare_captures(SCENES, capture_result, None, project_id="1")

    assert finding.status == STATUS_ERROR
    assert finding.items[0].severity == "error"
    assert "Cap_MainHall" in finding.items[0].message


def test_compare_captures_missing_outcome_is_error(tmp_path):
    capture_result = CaptureRunResult(outcomes=[])  # scene wasn't in the result at all

    finding = vrc.compare_captures(SCENES, capture_result, None, project_id="1")

    assert finding.status == STATUS_ERROR
    assert "no capture result" in finding.items[0].message


def test_compare_captures_whole_run_error_short_circuits(tmp_path):
    capture_result = CaptureRunResult(error="Unity did not finish capturing within 10 minutes")

    finding = vrc.compare_captures(SCENES, capture_result, None, project_id="1")

    assert finding.status == STATUS_ERROR
    assert finding.items == []
    assert "Capture failed" in finding.summary


def test_compare_captures_no_key_scenes():
    capture_result = CaptureRunResult(outcomes=[])
    finding = vrc.compare_captures([], capture_result, None, project_id="1")
    assert finding.status == STATUS_PASS
    assert finding.summary == "No key scenes configured to capture."


# --- run_visual_regression (orchestration) --------------------------------


def test_run_visual_regression_wires_capture_and_compare(tmp_path, monkeypatch):
    prev_dir = tmp_path / "prev"
    prev_dir.mkdir()
    _solid_png(prev_dir / "Main_Hall.png", (5, 5, 5))

    def fake_run_capture(unity_path, project_path, requests, timeout_s=600):
        outcomes = []
        for r in requests:
            _solid_png(r.output_path, (5, 5, 5))  # unchanged vs. previous
            outcomes.append(
                SceneCaptureOutcome(
                    scene_path=r.scene_path, output_path=r.output_path, succeeded=True
                )
            )
        return CaptureRunResult(outcomes=outcomes)

    monkeypatch.setattr(vrc, "run_capture", fake_run_capture)

    finding, capture_result = vrc.run_visual_regression(
        "Unity.exe",
        str(tmp_path),
        SCENES,
        tmp_path / "run1",
        project_id="1",
        previous_dir=prev_dir,
    )

    assert finding.status == STATUS_PASS
    assert len(capture_result.outcomes) == 1


# --- VisualRegressionCaptureService ----------------------------------------


def _setup_service():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    key_scenes = VisualRegressionKeySceneRepository(db)
    captures = VisualRegressionCaptureRepository(db)
    findings = AutomationFindingRepository(db)
    service = vrc.VisualRegressionCaptureService(key_scenes, captures, findings)
    project = projects.create("Moonlit Depths")
    return service, projects, project, captures


def test_service_raises_when_no_project_path(tmp_path):
    service, _projects, project, _captures = _setup_service()
    with pytest.raises(vrc.UnityUnavailableError):
        service.run(project, "Unity.exe")


def test_service_raises_when_no_key_scenes(tmp_path):
    service, projects, project, _captures = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")
    with pytest.raises(vrc.NoKeyScenesError):
        service.run(project, "Unity.exe")


def test_service_run_persists_finding_and_capture_history(tmp_path, monkeypatch):
    service, projects, project, _captures = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")
    service.add_key_scene(project.id, "Assets/Scenes/Main.unity", "Main Hall", "Cap_MainHall")

    def fake_run_visual_regression(
        unity_path, project_path, key_scenes, output_dir, project_id, **kwargs
    ):
        from spiced.automation.finding import Finding

        return (
            Finding(
                feature_id=vrc.FEATURE_ID,
                project_id=project_id,
                status=STATUS_PASS,
                summary="ok",
            ),
            CaptureRunResult(outcomes=[]),
        )

    monkeypatch.setattr(vrc, "run_visual_regression", fake_run_visual_regression)

    finding, record = service.run(project, "Unity.exe")

    assert record.feature_id == vrc.FEATURE_ID
    assert service.history(project.id) == [record]


def test_service_run_uses_previous_capture_dir(tmp_path, monkeypatch):
    service, projects, project, captures = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")
    service.add_key_scene(project.id, "Assets/Scenes/Main.unity", "Main Hall", "Cap_MainHall")
    captures.create(project.id, str(tmp_path / "old_run"))

    captured = {}

    def fake_run_visual_regression(
        unity_path, project_path, key_scenes, output_dir, project_id, **kwargs
    ):
        from spiced.automation.finding import Finding

        captured["previous_dir"] = kwargs.get("previous_dir")
        return (
            Finding(
                feature_id=vrc.FEATURE_ID,
                project_id=project_id,
                status=STATUS_PASS,
                summary="ok",
            ),
            CaptureRunResult(outcomes=[]),
        )

    monkeypatch.setattr(vrc, "run_visual_regression", fake_run_visual_regression)
    service.run(project, "Unity.exe")

    assert captured["previous_dir"] == str(tmp_path / "old_run")


# --- CLI ---------------------------------------------------------------


def test_cli_reads_scenes_config_and_prints_summary(tmp_path, monkeypatch, capsys):
    scenes_config = tmp_path / "scenes.json"
    scenes_config.write_text(
        json.dumps(
            [{"scene_path": "Assets/Scenes/Main.unity", "label": "Main Hall", "marker_name": "M"}]
        ),
        encoding="utf-8",
    )

    def fake_run_visual_regression(
        unity_path, project_path, key_scenes, output_dir, project_id, **kwargs
    ):
        from spiced.automation.finding import Finding

        return (
            Finding(
                feature_id=vrc.FEATURE_ID,
                project_id=project_id,
                status=STATUS_PASS,
                summary="Captured 1 key scene(s); no unexpected changes vs. the previous build.",
            ),
            CaptureRunResult(outcomes=[]),
        )

    monkeypatch.setattr(vrc, "run_visual_regression", fake_run_visual_regression)

    exit_code = vrc._cli(
        [
            "Unity.exe",
            str(tmp_path),
            "--scenes-config",
            str(scenes_config),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no unexpected changes" in out


def test_cli_bad_scenes_config_reports_error(tmp_path, capsys):
    exit_code = vrc._cli(
        [
            "Unity.exe",
            str(tmp_path),
            "--scenes-config",
            str(tmp_path / "does_not_exist.json"),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "scenes-config" in err
