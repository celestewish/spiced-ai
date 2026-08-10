"""Tests for automation.retopology_assist (Implementation Bible, Feature
10). Mesh loading/validation (via automation.uv_lod_generation.load_mesh,
reused from Feature 8) runs for real against trimesh-generated meshes. The
Blender subprocess call itself is monkeypatched -- no real Blender install
is required or assumed here, matching how Feature 9 mocks the RenderDoc
worker at the same boundary (see that module's own "UNVERIFIED" caveat,
which this feature's module docstring repeats for the same honest reason:
no Blender install is available in this environment either)."""

from __future__ import annotations

import json
import subprocess

import pytest
import trimesh

from spiced.automation import retopology_assist as ra
from spiced.automation.finding import STATUS_ERROR, STATUS_FLAGGED, STATUS_PASS
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _write_obj(path, subdivisions=1):
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions)
    mesh.export(str(path))


def _fake_result_json(tmp_path, **overrides):
    data = {
        "before_face_count": 320,
        "after_face_count": 5000,
        "quad_count": 4800,
        "triangle_count": 200,
        "other_polygon_count": 0,
        "non_manifold_edge_count": 0,
        "output_path": str(tmp_path / "out.obj"),
    }
    data.update(overrides)
    return data


# --- find_blender_executable -------------------------------------------


def test_find_blender_executable_raises_when_not_found(monkeypatch):
    monkeypatch.setattr(ra.shutil, "which", lambda name: None)
    with pytest.raises(ra.BlenderNotAvailableError):
        ra.find_blender_executable()


def test_find_blender_executable_uses_explicit_path(tmp_path):
    fake_blender = tmp_path / "blender.exe"
    fake_blender.write_text("x")
    assert ra.find_blender_executable(str(fake_blender)) == str(fake_blender)


def test_find_blender_executable_explicit_path_missing_raises():
    with pytest.raises(ra.BlenderNotAvailableError):
        ra.find_blender_executable("/no/such/blender")


def test_find_blender_executable_found_on_path(monkeypatch):
    monkeypatch.setattr(ra.shutil, "which", lambda name: "/usr/bin/blender")
    assert ra.find_blender_executable() == "/usr/bin/blender"


# --- run_retopology_worker (subprocess boundary) -------------------------


def test_run_retopology_worker_reads_real_result_file(tmp_path, monkeypatch):
    def fake_run(command, timeout, capture_output):
        # The real worker script would write to the 4th positional path
        # after "--"; find it and write our fake stats there instead.
        result_path = command[command.index("--") + 4]
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(_fake_result_json(tmp_path), f)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(ra.subprocess, "run", fake_run)

    result = ra.run_retopology_worker(
        "blender", tmp_path / "in.obj", tmp_path / "out.obj", 5000
    )

    assert result.succeeded
    assert result.stats.after_face_count == 5000
    assert result.stats.quad_ratio == pytest.approx(4800 / 5000)


def test_run_retopology_worker_crash_becomes_error_not_exception(monkeypatch, tmp_path):
    """A worker subprocess that exits non-zero (standing in for a real
    native QuadriFlow crash) must become a reported error, not raise --
    matches Feature 8's identical crash-isolation contract."""

    def fake_run(command, timeout, capture_output):
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"simulated crash")

    monkeypatch.setattr(ra.subprocess, "run", fake_run)

    result = ra.run_retopology_worker("blender", tmp_path / "in.obj", tmp_path / "out.obj", 5000)

    assert result.succeeded is False
    assert "simulated crash" in result.error


def test_run_retopology_worker_timeout_becomes_error(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(ra.subprocess, "run", fake_run)

    result = ra.run_retopology_worker(
        "blender", tmp_path / "in.obj", tmp_path / "out.obj", 5000, timeout_s=5
    )
    assert result.succeeded is False
    assert "5s" in result.error


def test_run_retopology_worker_missing_blender_binary_becomes_error(monkeypatch, tmp_path):
    def fake_run(command, timeout, capture_output):
        raise OSError("no such file")

    monkeypatch.setattr(ra.subprocess, "run", fake_run)

    result = ra.run_retopology_worker(
        "/no/blender", tmp_path / "in.obj", tmp_path / "out.obj", 5000
    )
    assert result.succeeded is False
    assert "Could not launch Blender" in result.error


# --- build_finding --------------------------------------------------------


def test_build_finding_pass_when_majority_quad_and_manifold_clean(tmp_path):
    result = ra.RetopologyWorkerResult(
        stats=ra.RetopologyStats(**_fake_result_json(tmp_path))
    )
    finding = ra.build_finding(result, "1", "mesh.obj", target_face_count=5000)
    assert finding.status == STATUS_PASS


def test_build_finding_flags_non_manifold_edges(tmp_path):
    result = ra.RetopologyWorkerResult(
        stats=ra.RetopologyStats(**_fake_result_json(tmp_path, non_manifold_edge_count=12))
    )
    finding = ra.build_finding(result, "1", "mesh.obj", target_face_count=5000)
    assert finding.status == STATUS_FLAGGED
    non_manifold_items = [
        i for i in finding.items if i.detail["issue_type"] == "non_manifold_edges"
    ]
    assert non_manifold_items[0].severity == "warning"


def test_build_finding_flags_majority_triangle_output(tmp_path):
    result = ra.RetopologyWorkerResult(
        stats=ra.RetopologyStats(
            **_fake_result_json(tmp_path, quad_count=100, triangle_count=4900)
        )
    )
    finding = ra.build_finding(result, "1", "mesh.obj", target_face_count=5000)
    assert finding.status == STATUS_FLAGGED
    quad_items = [i for i in finding.items if i.detail["issue_type"] == "quad_ratio"]
    assert quad_items[0].severity == "warning"


def test_build_finding_flags_face_count_far_from_target(tmp_path):
    result = ra.RetopologyWorkerResult(
        stats=ra.RetopologyStats(**_fake_result_json(tmp_path, after_face_count=1000))
    )
    finding = ra.build_finding(result, "1", "mesh.obj", target_face_count=5000)
    face_items = [i for i in finding.items if i.detail["issue_type"] == "face_count"]
    assert face_items[0].severity == "warning"
    assert face_items[0].detail["within_tolerance"] is False


def test_build_finding_error_result_is_error_status():
    result = ra.RetopologyWorkerResult(error="Blender's remesh failed (exit code 1).")
    finding = ra.build_finding(result, "1", "mesh.obj", target_face_count=5000)
    assert finding.status == STATUS_ERROR


# --- run_retopology_assist (end to end, mesh-format + Blender resolution) --


def test_run_retopology_assist_unsupported_format_is_error(tmp_path):
    mesh_path = tmp_path / "model.fbx"
    mesh_path.write_bytes(b"fake fbx")

    result = ra.run_retopology_assist(mesh_path, "1")
    assert result.finding.status == STATUS_ERROR
    assert "fbx" in result.finding.summary.lower() or ".fbx" in result.finding.summary


def test_run_retopology_assist_no_blender_is_clear_actionable_error(tmp_path, monkeypatch):
    mesh_path = tmp_path / "sphere.obj"
    _write_obj(mesh_path)
    monkeypatch.setattr(ra.shutil, "which", lambda name: None)

    result = ra.run_retopology_assist(mesh_path, "1")

    assert result.finding.status == STATUS_ERROR
    assert "Blender" in result.finding.summary
    assert result.output_path is None


def test_run_retopology_assist_end_to_end_success(tmp_path, monkeypatch):
    mesh_path = tmp_path / "sphere.obj"
    _write_obj(mesh_path)
    monkeypatch.setattr(ra.shutil, "which", lambda name: "/usr/bin/blender")

    def fake_run(command, timeout, capture_output):
        result_path = command[command.index("--") + 4]
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(_fake_result_json(tmp_path), f)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(ra.subprocess, "run", fake_run)

    result = ra.run_retopology_assist(mesh_path, "1", target_face_count=5000)

    assert result.finding.status == STATUS_PASS
    assert result.output_path is not None


# --- RetopologyAssistService ------------------------------------------------


def test_service_retopologize_persists_finding(tmp_path, monkeypatch):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    service = ra.RetopologyAssistService(findings)

    def fake_run_retopology_assist(mesh_path, project_id, **kwargs):
        finding = ra.Finding(
            feature_id=ra.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )
        return ra.RetopologyRunResult(finding=finding, output_path="out.obj")

    monkeypatch.setattr(ra, "run_retopology_assist", fake_run_retopology_assist)

    result, record = service.retopologize(project, tmp_path / "sphere.obj")
    assert record.feature_id == ra.FEATURE_ID
    assert findings.list_for_project(project.id) == [record]


def test_service_history_filters_by_feature_id():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    service = ra.RetopologyAssistService(findings)
    findings.create(
        project.id,
        ra.Finding(feature_id=ra.FEATURE_ID, project_id=str(project.id), status=STATUS_PASS,
                   summary="a"),
    )
    findings.create(
        project.id,
        ra.Finding(feature_id="art.other", project_id=str(project.id), status=STATUS_PASS,
                   summary="b"),
    )
    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].feature_id == ra.FEATURE_ID


# --- CLI --------------------------------------------------------------------


def test_cli_reports_missing_blender_cleanly(tmp_path, monkeypatch, capsys):
    mesh_path = tmp_path / "sphere.obj"
    _write_obj(mesh_path)
    monkeypatch.setattr(ra.shutil, "which", lambda name: None)

    exit_code = ra._cli([str(mesh_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "Blender" in out


def test_cli_json_flag_prints_finding_dict(tmp_path, monkeypatch, capsys):
    mesh_path = tmp_path / "sphere.obj"
    _write_obj(mesh_path)
    monkeypatch.setattr(ra.shutil, "which", lambda name: "/usr/bin/blender")

    def fake_run(command, timeout, capture_output):
        result_path = command[command.index("--") + 4]
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(_fake_result_json(tmp_path), f)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(ra.subprocess, "run", fake_run)

    exit_code = ra._cli([str(mesh_path), "--json"])
    out = capsys.readouterr().out

    assert exit_code == 0
    parsed = json.loads(out)
    assert parsed["feature_id"] == ra.FEATURE_ID
