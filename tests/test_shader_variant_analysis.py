"""Tests for automation.shader_variant_analysis (Implementation Bible,
Feature 6). The Unity call (connectors.unity_shader_variant_export.run_export)
is monkeypatched -- no real Unity install is required. find_shader_paths
runs for real against a synthetic Assets/ tree."""

from __future__ import annotations

import json

from spiced.automation import shader_variant_analysis as sva
from spiced.automation.finding import STATUS_ERROR, STATUS_FLAGGED, STATUS_PASS
from spiced.connectors.unity_shader_variant_export import (
    ShaderVariantOutcome,
    ShaderVariantRunResult,
)
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

# --- to_unity_asset_path / find_shader_paths --------------------------------


def test_to_unity_asset_path_relative(tmp_path):
    project_root = tmp_path / "proj"
    shader = project_root / "Assets" / "Shaders" / "Toon.shader"
    shader.parent.mkdir(parents=True)
    shader.write_text("Shader {}", encoding="utf-8")

    assert sva.to_unity_asset_path(shader, project_root) == "Assets/Shaders/Toon.shader"


def test_find_shader_paths_finds_only_shader_files(tmp_path):
    assets = tmp_path / "Assets"
    (assets / "Shaders").mkdir(parents=True)
    (assets / "Shaders" / "Toon.shader").write_text("Shader {}", encoding="utf-8")
    (assets / "Shaders" / "Toon.shader.meta").write_text("guid: x", encoding="utf-8")
    (assets / "Textures").mkdir()
    (assets / "Textures" / "wall.png").write_bytes(b"x")

    paths = sva.find_shader_paths(tmp_path)

    assert paths == ["Assets/Shaders/Toon.shader"]


def test_find_shader_paths_no_assets_folder(tmp_path):
    assert sva.find_shader_paths(tmp_path) == []


# --- build_finding -----------------------------------------------------


def test_build_finding_whole_run_error():
    result = ShaderVariantRunResult(error="Unity did not finish within 10 minutes")
    finding = sva.build_finding(result, project_id="1")
    assert finding.status == STATUS_ERROR
    assert finding.items == []
    assert "export failed" in finding.summary


def test_build_finding_per_shader_failure_is_error():
    result = ShaderVariantRunResult(
        outcomes=[
            ShaderVariantOutcome(
                shader_path="Assets/Broken.shader", succeeded=False, error="bad shader"
            )
        ]
    )
    finding = sva.build_finding(result, project_id="1")
    assert finding.status == STATUS_ERROR
    assert finding.items[0].severity == "error"


def test_build_finding_flags_over_threshold():
    result = ShaderVariantRunResult(
        outcomes=[
            ShaderVariantOutcome(
                shader_path="Assets/Bloated.shader",
                succeeded=True,
                variant_count=500,
                pass_count=3,
            )
        ]
    )
    finding = sva.build_finding(result, project_id="1", threshold=100)
    assert finding.status == STATUS_FLAGGED
    item = finding.items[0]
    assert item.severity == "warning"
    assert item.detail["variant_count"] == 500
    assert item.detail["estimated_compile_time_ms"] == 500 * sva.DEFAULT_MS_PER_VARIANT
    assert item.detail["top_offender_rank"] == 1


def test_build_finding_under_threshold_is_info():
    result = ShaderVariantRunResult(
        outcomes=[
            ShaderVariantOutcome(
                shader_path="Assets/Simple.shader", succeeded=True, variant_count=4, pass_count=1
            )
        ]
    )
    finding = sva.build_finding(result, project_id="1", threshold=100)
    assert finding.status == STATUS_PASS
    assert finding.items[0].severity == "info"


def test_build_finding_sorts_worst_offenders_first():
    result = ShaderVariantRunResult(
        outcomes=[
            ShaderVariantOutcome(
                shader_path="Assets/Small.shader", succeeded=True, variant_count=10, pass_count=1
            ),
            ShaderVariantOutcome(
                shader_path="Assets/Huge.shader", succeeded=True, variant_count=900, pass_count=1
            ),
        ]
    )
    finding = sva.build_finding(result, project_id="1", threshold=100)
    assert finding.items[0].asset_path == "Assets/Huge.shader"
    assert finding.items[0].detail["top_offender_rank"] == 1


def test_build_finding_used_shader_names_flags_unused():
    result = ShaderVariantRunResult(
        outcomes=[
            ShaderVariantOutcome(
                shader_path="Assets/Unused.shader", succeeded=True, variant_count=4, pass_count=1
            )
        ]
    )
    finding = sva.build_finding(
        result, project_id="1", threshold=100, used_shader_names={"Assets/Other.shader"}
    )
    assert finding.status == STATUS_FLAGGED
    assert "used-shaders list" in finding.items[0].message


def test_build_finding_used_shader_names_not_flagged_when_present():
    result = ShaderVariantRunResult(
        outcomes=[
            ShaderVariantOutcome(
                shader_path="Assets/Used.shader", succeeded=True, variant_count=4, pass_count=1
            )
        ]
    )
    finding = sva.build_finding(
        result, project_id="1", threshold=100, used_shader_names={"Assets/Used.shader"}
    )
    assert finding.status == STATUS_PASS


def test_summarize_no_shaders():
    assert sva._summarize([], 0) == "No .shader files found to analyze."


# --- analyze_shader_variants (orchestration) --------------------------------


def test_analyze_shader_variants_no_shaders_short_circuits(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(sva, "run_export", lambda *a, **k: called.append(1))

    finding = sva.analyze_shader_variants("Unity.exe", tmp_path, "1")

    assert finding.status == STATUS_PASS
    assert called == []  # never launched Unity when there's nothing to check


def test_analyze_shader_variants_runs_export(tmp_path, monkeypatch):
    assets = tmp_path / "Assets"
    assets.mkdir()
    (assets / "Toon.shader").write_text("Shader {}", encoding="utf-8")

    def fake_run_export(unity_path, project_path, shader_paths, timeout_s=600):
        assert shader_paths == ["Assets/Toon.shader"]
        return ShaderVariantRunResult(
            outcomes=[
                ShaderVariantOutcome(
                    shader_path="Assets/Toon.shader", succeeded=True, variant_count=4, pass_count=1
                )
            ]
        )

    monkeypatch.setattr(sva, "run_export", fake_run_export)

    finding = sva.analyze_shader_variants("Unity.exe", tmp_path, "1")

    assert finding.status == STATUS_PASS


# --- ShaderVariantAnalysisService --------------------------------------------


def _setup_service():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    service = sva.ShaderVariantAnalysisService(findings)
    project = projects.create("Moonlit Depths")
    return service, projects, project


def test_service_uses_default_threshold(tmp_path, monkeypatch):
    service, projects, project = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")

    captured = {}

    def fake_analyze(unity_path, project_path, project_id, **kwargs):
        captured.update(kwargs)
        from spiced.automation.finding import Finding

        return Finding(
            feature_id=sva.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(sva, "analyze_shader_variants", fake_analyze)
    service.scan(project, "Unity.exe")

    assert captured["threshold"] == sva.DEFAULT_VARIANT_THRESHOLD


def test_service_uses_project_threshold(tmp_path, monkeypatch):
    service, projects, project = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")
    project = projects.set_shader_variant_threshold(project.id, 42)

    captured = {}

    def fake_analyze(unity_path, project_path, project_id, **kwargs):
        captured.update(kwargs)
        from spiced.automation.finding import Finding

        return Finding(
            feature_id=sva.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(sva, "analyze_shader_variants", fake_analyze)
    service.scan(project, "Unity.exe")

    assert captured["threshold"] == 42


def test_service_persists_finding_and_history(tmp_path, monkeypatch):
    service, projects, project = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")

    def fake_analyze(unity_path, project_path, project_id, **kwargs):
        from spiced.automation.finding import Finding

        return Finding(
            feature_id=sva.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(sva, "analyze_shader_variants", fake_analyze)
    finding, record = service.scan(project, "Unity.exe")

    assert record.feature_id == sva.FEATURE_ID
    assert service.history(project.id) == [record]


# --- CLI ---------------------------------------------------------------


def test_cli_prints_summary(tmp_path, monkeypatch, capsys):
    def fake_analyze(unity_path, project_path, project_id, **kwargs):
        from spiced.automation.finding import Finding

        return Finding(
            feature_id=sva.FEATURE_ID,
            project_id=project_id,
            status=STATUS_PASS,
            summary="Analyzed 1 shader(s); no variant bloat found.",
        )

    monkeypatch.setattr(sva, "analyze_shader_variants", fake_analyze)
    exit_code = sva._cli(["Unity.exe", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no variant bloat found" in out


def test_cli_json_flag(tmp_path, monkeypatch, capsys):
    def fake_analyze(unity_path, project_path, project_id, **kwargs):
        from spiced.automation.finding import Finding

        return Finding(
            feature_id=sva.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(sva, "analyze_shader_variants", fake_analyze)
    exit_code = sva._cli(["Unity.exe", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert exit_code == 0
    assert parsed["feature_id"] == sva.FEATURE_ID
