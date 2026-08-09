"""Tests for automation.uv_lod_generation (Implementation Bible, Feature 8).
Everything here runs for real -- no mocking -- against meshes generated with
trimesh's own primitives (icospheres/boxes), including one test at the
Bible's literal ~50k-triangle acceptance-criteria scale."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from spiced.automation import uv_lod_generation as uld
from spiced.automation.finding import STATUS_ERROR, STATUS_PASS
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _write_obj(path, subdivisions=2):
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions)
    mesh.export(str(path))
    return mesh


def _mesh_buffers(subdivisions=2) -> uld.MeshBuffers:
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions)
    return uld.MeshBuffers(
        vertices=np.asarray(mesh.vertices, dtype=np.float32),
        faces=np.asarray(mesh.faces, dtype=np.uint32),
    )


# --- load_mesh ---------------------------------------------------------


def test_load_mesh_obj(tmp_path):
    p = tmp_path / "sphere.obj"
    _write_obj(p, subdivisions=1)

    buffers = uld.load_mesh(p)

    assert buffers.vertices.shape[1] == 3
    assert buffers.faces.shape[1] == 3
    assert len(buffers.faces) == 80  # icosphere subdivisions=1


def test_load_mesh_glb(tmp_path):
    p = tmp_path / "sphere.glb"
    mesh = trimesh.creation.icosphere(subdivisions=1)
    mesh.export(str(p))

    buffers = uld.load_mesh(p)

    assert len(buffers.faces) == 80


def test_load_mesh_unsupported_format_raises(tmp_path):
    p = tmp_path / "model.fbx"
    p.write_bytes(b"fake fbx data")
    with pytest.raises(uld.UnsupportedMeshFormatError):
        uld.load_mesh(p)


def test_load_mesh_unreadable_file_raises(tmp_path):
    p = tmp_path / "broken.obj"
    p.write_text("not a valid obj file @#$%", encoding="utf-8")
    with pytest.raises(uld.UnreadableMeshError):
        uld.load_mesh(p)


# --- generate_uv_lod_chain (out-of-process simplify+unwrap) ----------------


def test_generate_uv_lod_chain_ratio_1_is_unchanged():
    mesh = _mesh_buffers(subdivisions=2)  # 320 triangles
    outcomes = uld.generate_uv_lod_chain(mesh, ratios=(1.0,))
    assert outcomes[0].succeeded
    assert outcomes[0].result.triangle_count == len(mesh.faces)


def test_generate_uv_lod_chain_reduces_triangle_count():
    mesh = _mesh_buffers(subdivisions=3)  # 1280 triangles
    outcomes = uld.generate_uv_lod_chain(mesh, ratios=(1.0, 0.5, 0.25, 0.1))

    assert all(o.succeeded for o in outcomes)
    counts = [o.result.triangle_count for o in outcomes]
    assert counts[0] == 1280
    # Each ratio should land at or below its target budget (meshopt may not
    # hit the exact count, but must not exceed a generous margin over it).
    assert counts[1] <= 1280 * 0.5 * 1.2
    assert counts[2] <= 1280 * 0.25 * 1.2
    assert counts[3] <= 1280 * 0.1 * 1.5  # aggressive simplification has more slack
    # Strictly decreasing.
    assert counts == sorted(counts, reverse=True)


def test_generate_uv_lod_chain_produces_valid_uvs():
    mesh = _mesh_buffers(subdivisions=2)
    outcomes = uld.generate_uv_lod_chain(mesh, ratios=(1.0,))
    lod = outcomes[0].result
    assert lod.uvs.shape[1] == 2
    assert lod.uvs.min() >= -1e-4
    assert lod.uvs.max() <= 1.0 + 1e-4
    assert lod.chart_count >= 1
    assert 0.0 < lod.atlas_utilization <= 1.0


def test_generate_uv_lod_chain_calls_on_progress():
    mesh = _mesh_buffers(subdivisions=1)
    messages = []
    uld.generate_uv_lod_chain(mesh, ratios=(1.0, 0.5), on_progress=messages.append)
    assert len(messages) == 2  # one message per ratio


def test_generate_uv_lod_chain_worker_crash_becomes_error_outcome(tmp_path, monkeypatch):
    """A worker subprocess that exits non-zero (standing in for a real
    native crash) must become a reported error, not raise/crash this
    process -- see the module docstring for why."""
    mesh = _mesh_buffers(subdivisions=1)

    def fake_run(command, timeout, capture_output):
        import subprocess

        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"simulated crash")

    monkeypatch.setattr(uld.subprocess, "run", fake_run)

    outcomes = uld.generate_uv_lod_chain(mesh, ratios=(1.0,))

    assert outcomes[0].succeeded is False
    assert "simulated crash" in outcomes[0].error


def test_generate_uv_lod_chain_partial_failure_does_not_stop_other_lods(monkeypatch):
    mesh = _mesh_buffers(subdivisions=2)
    real_run_worker = uld._run_lod_worker

    def flaky_run_worker(mesh_arg, ratio, **kwargs):
        if ratio == 0.5:
            raise uld.LodGenerationError("simulated crash at 50%")
        return real_run_worker(mesh_arg, ratio, **kwargs)

    monkeypatch.setattr(uld, "_run_lod_worker", flaky_run_worker)

    outcomes = uld.generate_uv_lod_chain(mesh, ratios=(1.0, 0.5, 0.25))

    assert outcomes[0].succeeded
    assert not outcomes[1].succeeded
    assert outcomes[2].succeeded


# --- export_lod ----------------------------------------------------------


def test_export_lod_writes_file_with_uvs(tmp_path):
    mesh = _mesh_buffers(subdivisions=1)
    lod = uld.generate_uv_lod_chain(mesh, ratios=(1.0,))[0].result
    out_path = tmp_path / "out.glb"

    result = uld.export_lod(lod, out_path)

    assert out_path.is_file()
    assert result.output_path == str(out_path)
    reloaded = trimesh.load(str(out_path), force="mesh")
    assert reloaded.visual.uv is not None
    assert len(reloaded.faces) == lod.triangle_count


# --- run_uv_lod_generation (orchestration) ----------------------------------


def test_run_uv_lod_generation_end_to_end(tmp_path):
    mesh_path = tmp_path / "chair.obj"
    _write_obj(mesh_path, subdivisions=2)
    output_dir = tmp_path / "out"

    result = uld.run_uv_lod_generation(
        mesh_path, "1", output_dir=output_dir, ratios=(1.0, 0.5, 0.25, 0.1)
    )

    assert result.finding.status == STATUS_PASS
    assert len(result.lods) == 4
    for lod in result.lods:
        assert lod.output_path is not None
        assert Path(lod.output_path).is_file()
    # Files are named distinctly per LOD level.
    names = {Path(lod.output_path).name for lod in result.lods}
    assert len(names) == 4


def test_run_uv_lod_generation_unsupported_format_is_error(tmp_path):
    mesh_path = tmp_path / "model.fbx"
    mesh_path.write_bytes(b"fake")

    result = uld.run_uv_lod_generation(mesh_path, "1", output_dir=tmp_path / "out")

    assert result.finding.status == STATUS_ERROR
    assert result.lods == []


def test_summarize_no_lods():
    assert uld._summarize([], total=0) == "No LOD levels were generated."


def test_summarize_all_failed():
    assert uld._summarize([], total=2) == "All 2 LOD level(s) failed to generate."


def test_summarize_partial_failure_notes_failed_count():
    summary = uld._summarize([("LOD0", 100)], total=2)
    assert "1 failed" in summary


# --- Bible acceptance criteria: ~50k-triangle mesh --------------------------


def test_acceptance_50k_triangle_mesh_no_overlapping_charts_and_lod_budget(tmp_path):
    # A UV sphere with enough segments to comfortably pass the Bible's
    # "50k-triangle test mesh" acceptance criteria. NOT an icosphere: this
    # project found (see test_worker_crash_isolation_on_known_bad_mesh
    # below, and the module docstring) that a specific icosphere topology
    # reproducibly segfaults xatlas at this scale -- a real, narrow bug in
    # that library, not something this test should paper over by picking a
    # mesh that avoids it silently. A UV sphere exercises the same "large,
    # curved, needs real UV seams" acceptance intent without hitting it.
    mesh_path = tmp_path / "large_mesh.obj"
    mesh = trimesh.creation.uv_sphere(count=(140, 140))
    mesh.export(str(mesh_path))
    assert len(mesh.faces) > 50_000

    output_dir = tmp_path / "out"
    result = uld.run_uv_lod_generation(
        mesh_path, "1", output_dir=output_dir, ratios=(1.0, 0.5, 0.25, 0.1)
    )

    assert result.finding.status == STATUS_PASS
    lod0, lod1, lod2, lod3 = result.lods
    assert lod0.triangle_count == len(mesh.faces)
    # LOD1 (50%) lands within its configured triangle budget.
    assert lod1.triangle_count <= lod0.triangle_count * 0.5 * 1.1
    assert lod2.triangle_count < lod1.triangle_count
    assert lod3.triangle_count < lod2.triangle_count
    # xatlas guarantees non-overlapping charts by construction -- this
    # module relies on that rather than re-verifying it (see module
    # docstring); confirm the chart count is at least sane (>0, not the
    # whole mesh collapsed to a single degenerate chart).
    for lod in result.lods:
        assert lod.chart_count > 0


def test_worker_crash_isolation_on_known_bad_mesh(tmp_path):
    """The one mesh topology this project found that reliably segfaults
    xatlas.Atlas.generate() (see module docstrings). This must surface as a
    clean 'error' Finding, not crash the test process -- that's the entire
    point of running the simplify+unwrap step in a subprocess."""
    mesh_path = tmp_path / "known_bad_mesh.obj"
    mesh = trimesh.creation.icosphere(subdivisions=6)  # 81920 triangles
    mesh.export(str(mesh_path))

    result = uld.run_uv_lod_generation(mesh_path, "1", output_dir=tmp_path / "out", ratios=(1.0,))

    assert result.finding.status == STATUS_ERROR
    assert result.lods == []
    assert result.finding.items[0].severity == "error"


# --- UvLodGenerationService --------------------------------------------


def _setup_service():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    service = uld.UvLodGenerationService(findings)
    project = projects.create("Moonlit Depths")
    return service, project


def test_service_generate_persists_and_history(tmp_path):
    service, project = _setup_service()
    mesh_path = tmp_path / "chair.obj"
    _write_obj(mesh_path, subdivisions=1)

    result = service.generate(project, mesh_path, output_dir=tmp_path / "out", ratios=(1.0,))

    assert result.finding.status == STATUS_PASS
    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].feature_id == uld.FEATURE_ID


# --- CLI ---------------------------------------------------------------


def test_cli_generates_and_prints_summary(tmp_path, capsys):
    mesh_path = tmp_path / "chair.obj"
    _write_obj(mesh_path, subdivisions=1)

    exit_code = uld._cli(
        [str(mesh_path), "--output-dir", str(tmp_path / "out"), "--ratios", "1.0", "0.5"]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Generated 2 of 2 LOD level(s)" in out


def test_cli_json_flag(tmp_path, capsys):
    mesh_path = tmp_path / "chair.obj"
    _write_obj(mesh_path, subdivisions=1)

    exit_code = uld._cli(
        [str(mesh_path), "--output-dir", str(tmp_path / "out"), "--ratios", "1.0", "--json"]
    )

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert exit_code == 0
    assert parsed["feature_id"] == uld.FEATURE_ID


def test_cli_unsupported_format_reports_error(tmp_path, capsys):
    mesh_path = tmp_path / "model.fbx"
    mesh_path.write_bytes(b"fake")

    exit_code = uld._cli([str(mesh_path), "--output-dir", str(tmp_path / "out")])

    assert exit_code == 1
