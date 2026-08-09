"""Tests for automation.asset_technical_qa (Implementation Bible, Feature 3).
Local checks run for real against tiny synthetic images/.meta files (same
fixtures as tests/test_asset_review_queue.py); the pivot-check's Unity call
(connectors.unity_asset_export.run_export) is monkeypatched -- no real Unity
install is required."""

from __future__ import annotations

import json

from PIL import Image

from spiced.automation import asset_technical_qa as atq
from spiced.automation.finding import STATUS_FLAGGED, STATUS_PASS
from spiced.connectors.unity_asset_export import AssetExportOutcome, AssetExportRunResult
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

_TEXTURE_META_MIPMAPS_DISABLED = """fileFormatVersion: 2
guid: dcfda5a0b6ea04ccfab148149ab12d4a
TextureImporter:
  serializedVersion: 4
  mipmaps:
    mipMapMode: 0
    enableMipMap: 0
    sRGBTexture: 0
"""


def _make_png(path, size=(64, 64), color=(255, 0, 0)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=color).save(path)


# --- to_unity_asset_path ---------------------------------------------------


def test_to_unity_asset_path_relative(tmp_path):
    project_root = tmp_path / "proj"
    asset = project_root / "Assets" / "Models" / "Chair.fbx"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"fake fbx")

    rel = atq.to_unity_asset_path(asset, project_root)

    assert rel == "Assets/Models/Chair.fbx"


def test_to_unity_asset_path_outside_project_is_none(tmp_path):
    outside = tmp_path / "elsewhere" / "Chair.fbx"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"x")

    assert atq.to_unity_asset_path(outside, tmp_path / "proj") is None


# --- check_naming -----------------------------------------------------------


def test_check_naming_valid_name_returns_none(tmp_path):
    p = tmp_path / "GoodName.png"
    p.write_bytes(b"x")
    assert atq.check_naming(p) is None


def test_check_naming_invalid_name_flags(tmp_path):
    p = tmp_path / "bad name!!.png"
    p.write_bytes(b"x")
    item = atq.check_naming(p)
    assert item is not None
    assert item.severity == "warning"
    assert item.detail["issue_type"] == "naming"


# --- scan_local ---------------------------------------------------------


def test_scan_local_clean_asset_is_info(tmp_path):
    p = tmp_path / "GoodTexture.png"
    _make_png(p, size=(64, 64))  # power-of-two, small, valid name

    items = atq.scan_local([p], project_root=None)

    assert len(items) == 1
    assert items[0].severity == "info"


def test_scan_local_flags_non_po2_and_bad_naming(tmp_path):
    p = tmp_path / "bad name.png"
    _make_png(p, size=(50, 70))  # not power-of-two

    items = atq.scan_local([p], project_root=None)

    issue_types = {i.detail.get("issue_type") for i in items}
    assert "resolution_po2" in issue_types
    assert "naming" in issue_types
    assert all(i.severity == "warning" for i in items)


def test_scan_local_reads_mipmap_setting_from_meta(tmp_path):
    project_root = tmp_path
    assets_dir = project_root / "Assets"
    p = assets_dir / "Wall.png"
    _make_png(p, size=(64, 64))
    (p.parent / (p.name + ".meta")).write_text(_TEXTURE_META_MIPMAPS_DISABLED, encoding="utf-8")

    items = atq.scan_local([p], project_root=project_root)

    issue_types = {i.detail.get("issue_type") for i in items}
    assert "mipmaps_disabled" in issue_types


def test_scan_local_unreadable_file_is_error(tmp_path):
    missing = tmp_path / "does_not_exist.png"

    items = atq.scan_local([missing], project_root=None)

    assert len(items) == 1
    assert items[0].severity == "error"


def test_scan_local_custom_naming_pattern(tmp_path):
    p = tmp_path / "lowercase_name.png"
    _make_png(p, size=(64, 64))

    # Require PascalCase -- lowercase_name should fail this pattern.
    items = atq.scan_local([p], project_root=None, naming_pattern=r"^[A-Z][A-Za-z0-9]*$")

    assert any(i.detail.get("issue_type") == "naming" for i in items)


# --- scan_pivots ---------------------------------------------------------


def test_scan_pivots_flags_off_center(tmp_path, monkeypatch):
    project_root = tmp_path
    mesh = project_root / "Assets" / "Chair.fbx"
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(b"fake")

    def fake_run_export(unity_path, project_path, asset_paths, timeout_s=600):
        return AssetExportRunResult(
            outcomes=[
                AssetExportOutcome(
                    asset_path="Assets/Chair.fbx",
                    succeeded=True,
                    pivot_offset=0.5,
                    bounds_size=1.0,
                )
            ]
        )

    monkeypatch.setattr(atq, "run_export", fake_run_export)

    items = atq.scan_pivots("Unity.exe", project_root, [mesh], tolerance=0.1)

    assert len(items) == 1
    assert items[0].severity == "warning"
    assert items[0].detail["issue_type"] == "pivot_offset"


def test_scan_pivots_within_tolerance_no_flag(tmp_path, monkeypatch):
    project_root = tmp_path
    mesh = project_root / "Assets" / "Chair.fbx"
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(b"fake")

    def fake_run_export(unity_path, project_path, asset_paths, timeout_s=600):
        return AssetExportRunResult(
            outcomes=[
                AssetExportOutcome(
                    asset_path="Assets/Chair.fbx",
                    succeeded=True,
                    pivot_offset=0.02,
                    bounds_size=1.0,
                )
            ]
        )

    monkeypatch.setattr(atq, "run_export", fake_run_export)

    items = atq.scan_pivots("Unity.exe", project_root, [mesh], tolerance=0.1)

    assert items == []


def test_scan_pivots_per_asset_failure_is_error(tmp_path, monkeypatch):
    project_root = tmp_path
    mesh = project_root / "Assets" / "Broken.fbx"
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(b"fake")

    def fake_run_export(unity_path, project_path, asset_paths, timeout_s=600):
        return AssetExportRunResult(
            outcomes=[
                AssetExportOutcome(
                    asset_path="Assets/Broken.fbx", succeeded=False, error="no mesh found"
                )
            ]
        )

    monkeypatch.setattr(atq, "run_export", fake_run_export)

    items = atq.scan_pivots("Unity.exe", project_root, [mesh])

    assert items[0].severity == "error"
    assert "no mesh found" in items[0].message


def test_scan_pivots_whole_run_error(tmp_path, monkeypatch):
    project_root = tmp_path
    mesh = project_root / "Assets" / "Chair.fbx"
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(b"fake")

    def fake_run_export(unity_path, project_path, asset_paths, timeout_s=600):
        return AssetExportRunResult(error="Unity did not finish within 10 minutes")

    monkeypatch.setattr(atq, "run_export", fake_run_export)

    items = atq.scan_pivots("Unity.exe", project_root, [mesh])

    assert len(items) == 1
    assert items[0].severity == "error"


def test_scan_pivots_skips_meshes_outside_project(tmp_path):
    outside_mesh = tmp_path / "elsewhere" / "Chair.fbx"
    outside_mesh.parent.mkdir(parents=True)
    outside_mesh.write_bytes(b"fake")

    items = atq.scan_pivots("Unity.exe", tmp_path / "proj", [outside_mesh])

    assert items == []


def test_scan_pivots_no_meshes_returns_empty():
    assert atq.scan_pivots("Unity.exe", "some/project", []) == []


# --- run_asset_technical_qa (orchestration) --------------------------------


def test_run_asset_technical_qa_local_only_skips_pivot_check(tmp_path):
    _make_png(tmp_path / "Good.png", size=(64, 64))

    finding = atq.run_asset_technical_qa(tmp_path, project_id="1")

    assert finding.status == STATUS_PASS
    assert finding.feature_id == atq.FEATURE_ID


def test_run_asset_technical_qa_runs_pivot_check_when_unity_given(tmp_path, monkeypatch):
    project_root = tmp_path
    assets = project_root / "Assets"
    _make_png(assets / "Good.png", size=(64, 64))
    mesh = assets / "Chair.fbx"
    mesh.write_bytes(b"fake")

    calls = []

    def fake_run_export(unity_path, project_path, asset_paths, timeout_s=600):
        calls.append(asset_paths)
        return AssetExportRunResult(
            outcomes=[
                AssetExportOutcome(
                    asset_path="Assets/Chair.fbx", succeeded=True, pivot_offset=0.5, bounds_size=1.0
                )
            ]
        )

    monkeypatch.setattr(atq, "run_export", fake_run_export)

    finding = atq.run_asset_technical_qa(
        assets, project_id="1", project_root=project_root, unity_path="Unity.exe"
    )

    assert calls == [["Assets/Chair.fbx"]]
    assert finding.status == STATUS_FLAGGED
    assert any(i.detail.get("issue_type") == "pivot_offset" for i in finding.items)


def test_summarize_no_assets():
    assert atq._summarize([], 0) == "No assets found to scan."


# --- AssetTechnicalQaService ----------------------------------------------


def _setup_service():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    service = atq.AssetTechnicalQaService(findings)
    project = projects.create("Moonlit Depths")
    return service, projects, project


def test_service_uses_defaults_when_project_has_none(tmp_path, monkeypatch):
    service, projects, project = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")

    captured = {}

    def fake_run(folder_path, project_id, **kwargs):
        captured.update(kwargs)
        from spiced.automation.finding import Finding

        return Finding(
            feature_id=atq.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(atq, "run_asset_technical_qa", fake_run)
    service.scan(project, tmp_path)

    assert captured["naming_pattern"] == atq.DEFAULT_NAMING_PATTERN
    assert captured["pivot_tolerance"] == atq.DEFAULT_PIVOT_TOLERANCE


def test_service_uses_project_settings(tmp_path, monkeypatch):
    service, projects, project = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")
    project = projects.set_asset_qa_settings(project.id, r"^[A-Z][A-Za-z0-9]*$", 0.25)

    captured = {}

    def fake_run(folder_path, project_id, **kwargs):
        captured.update(kwargs)
        from spiced.automation.finding import Finding

        return Finding(
            feature_id=atq.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(atq, "run_asset_technical_qa", fake_run)
    service.scan(project, tmp_path)

    assert captured["naming_pattern"] == r"^[A-Z][A-Za-z0-9]*$"
    assert captured["pivot_tolerance"] == 0.25


def test_service_persists_finding_and_history(tmp_path, monkeypatch):
    service, projects, project = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")

    def fake_run(folder_path, project_id, **kwargs):
        from spiced.automation.finding import Finding

        return Finding(
            feature_id=atq.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(atq, "run_asset_technical_qa", fake_run)
    finding, record = service.scan(project, tmp_path)

    assert record.feature_id == atq.FEATURE_ID
    assert service.history(project.id) == [record]


# --- CLI ---------------------------------------------------------------


def test_cli_scans_folder_and_prints_summary(tmp_path, capsys):
    _make_png(tmp_path / "Good.png", size=(64, 64))

    exit_code = atq._cli([str(tmp_path), "--project-id", "1"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no technical issues found" in out


def test_cli_json_flag(tmp_path, capsys):
    _make_png(tmp_path / "Good.png", size=(64, 64))

    exit_code = atq._cli([str(tmp_path), "--json"])

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert exit_code == 0
    assert parsed["feature_id"] == atq.FEATURE_ID
