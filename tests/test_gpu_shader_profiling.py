"""Tests for automation.gpu_shader_profiling (Implementation Bible,
Feature 9). The RenderDoc capture-analysis step
(connectors.renderdoc_analysis.analyze_capture) is monkeypatched -- no real
RenderDoc install is required, or even possible to verify against (see that
module's docstring). Everything else -- budget computation, ranking,
Finding-building -- runs for real and is fully tested, matching the Bible's
acceptance criteria: a deliberately expensive shader must surface as the
top cost contributor."""

from __future__ import annotations

import json

import pytest

from spiced.automation import gpu_shader_profiling as gsp
from spiced.automation.finding import STATUS_ERROR, STATUS_FLAGGED, STATUS_PASS
from spiced.connectors.renderdoc_analysis import CaptureAnalysisResult, ShaderGpuStats
from spiced.core.hardware_simulation import HARDWARE_TIERS
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

# --- tier_budget_ms ---------------------------------------------------


def test_tier_budget_ms_scales_with_fps_factor():
    low = gsp.tier_budget_ms("Low-end PC")
    mid = gsp.tier_budget_ms("Mid-range PC")
    assert low < mid  # weaker tier gets a smaller budget


def test_tier_budget_ms_unknown_tier_raises():
    with pytest.raises(ValueError):
        gsp.tier_budget_ms("Fictional GPU")


def test_tier_budget_ms_matches_hardware_tiers_fps_factor():
    tier = "Handheld (Switch-like)"
    expected = (
        gsp.DEFAULT_FRAME_BUDGET_MS
        * HARDWARE_TIERS[tier]["fps_factor"]
        * gsp.DEFAULT_BUDGET_FRACTION
    )
    assert gsp.tier_budget_ms(tier) == pytest.approx(expected)


# --- build_finding (Bible acceptance criteria) ------------------------------


def test_build_finding_flags_the_expensive_shader_as_top_offender():
    # One deliberately expensive shader (an "unoptimized post-process
    # effect") among several cheap ones -- matches the Bible's acceptance
    # criteria almost verbatim.
    stats = [
        ShaderGpuStats(
            "Sprites/Default", gpu_time_ms=0.1, texture_bandwidth_bytes=1024, draw_call_count=20
        ),
        ShaderGpuStats(
            "UI/Default", gpu_time_ms=0.05, texture_bandwidth_bytes=512, draw_call_count=10
        ),
        ShaderGpuStats(
            "PostProcess/UnoptimizedBloom",
            gpu_time_ms=12.0,
            texture_bandwidth_bytes=50_000_000,
            draw_call_count=1,
        ),
    ]

    finding = gsp.build_finding(stats, project_id="1", tier="Low-end PC")

    assert finding.status == STATUS_FLAGGED
    top = finding.items[0]
    assert top.detail["shader_name"] == "PostProcess/UnoptimizedBloom"
    assert top.detail["top_offender_rank"] == 1
    assert top.severity == "warning"
    # Cheap shaders aren't flagged.
    cheap = [i for i in finding.items if i.detail["shader_name"] != "PostProcess/UnoptimizedBloom"]
    assert all(i.severity == "info" for i in cheap)


def test_build_finding_no_shaders_over_budget_passes():
    stats = [
        ShaderGpuStats("Cheap", gpu_time_ms=0.01, texture_bandwidth_bytes=100, draw_call_count=1)
    ]
    finding = gsp.build_finding(stats, project_id="1", tier="Low-end PC")
    assert finding.status == STATUS_PASS


def test_build_finding_explicit_budget_overrides_tier():
    stats = [ShaderGpuStats("A", gpu_time_ms=1.0, texture_bandwidth_bytes=0, draw_call_count=1)]
    # Absurdly high budget -- even a shader that would normally be flagged passes.
    finding = gsp.build_finding(stats, project_id="1", tier="Low-end PC", budget_ms=1000.0)
    assert finding.status == STATUS_PASS


def test_build_finding_empty_stats():
    finding = gsp.build_finding([], project_id="1")
    assert finding.status == STATUS_PASS
    assert finding.summary == "No shaders found in the capture."


# --- run_gpu_shader_profiling (orchestration) -------------------------------


def test_run_gpu_shader_profiling_propagates_capture_error(monkeypatch):
    def fake_analyze(rdc_path, pymodules_path, **kwargs):
        return CaptureAnalysisResult(error="RenderDoc isn't installed.")

    monkeypatch.setattr(gsp, "analyze_capture", fake_analyze)

    result = gsp.run_gpu_shader_profiling("capture.rdc", "pymodules", "1")

    assert result.finding.status == STATUS_ERROR
    assert result.stats == []


def test_run_gpu_shader_profiling_success(monkeypatch):
    def fake_analyze(rdc_path, pymodules_path, **kwargs):
        return CaptureAnalysisResult(
            stats=[
                ShaderGpuStats(
                    "Cheap", gpu_time_ms=0.01, texture_bandwidth_bytes=0, draw_call_count=1
                )
            ]
        )

    monkeypatch.setattr(gsp, "analyze_capture", fake_analyze)

    result = gsp.run_gpu_shader_profiling("capture.rdc", "pymodules", "1")

    assert result.finding.status == STATUS_PASS
    assert len(result.stats) == 1


# --- GpuShaderProfilingService --------------------------------------------


def _setup_service():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    service = gsp.GpuShaderProfilingService(findings)
    project = projects.create("Moonlit Depths")
    return service, projects, project


def test_service_uses_default_tier_and_budget(monkeypatch):
    service, _projects, project = _setup_service()

    def fake_analyze(rdc_path, pymodules_path, **kwargs):
        return CaptureAnalysisResult(
            stats=[
                ShaderGpuStats("A", gpu_time_ms=100.0, texture_bandwidth_bytes=0, draw_call_count=1)
            ]
        )

    monkeypatch.setattr(gsp, "analyze_capture", fake_analyze)
    result, record = service.profile(project, "capture.rdc", "pymodules")

    assert result.finding.items[0].detail["hardware_tier"] == gsp.DEFAULT_HARDWARE_TIER
    assert record.feature_id == gsp.FEATURE_ID


def test_service_uses_project_tier_and_budget(monkeypatch):
    service, projects, project = _setup_service()
    project = projects.set_gpu_shader_profiling_settings(project.id, 50.0, "Handheld (Switch-like)")

    def fake_analyze(rdc_path, pymodules_path, **kwargs):
        return CaptureAnalysisResult(
            stats=[
                ShaderGpuStats("A", gpu_time_ms=40.0, texture_bandwidth_bytes=0, draw_call_count=1)
            ]
        )

    monkeypatch.setattr(gsp, "analyze_capture", fake_analyze)
    result, _record = service.profile(project, "capture.rdc", "pymodules")

    assert result.finding.items[0].detail["hardware_tier"] == "Handheld (Switch-like)"
    assert result.finding.status == STATUS_PASS  # 40ms is under the 50ms explicit budget


def test_service_explicit_tier_overrides_project_default(monkeypatch):
    service, projects, project = _setup_service()
    project = projects.set_gpu_shader_profiling_settings(project.id, None, "Mid-range PC")

    def fake_analyze(rdc_path, pymodules_path, **kwargs):
        return CaptureAnalysisResult(stats=[])

    monkeypatch.setattr(gsp, "analyze_capture", fake_analyze)
    result, _record = service.profile(project, "capture.rdc", "pymodules", tier="Low-end PC")

    assert result.finding.summary == "No shaders found in the capture."


def test_service_history(monkeypatch):
    service, _projects, project = _setup_service()

    def fake_analyze(rdc_path, pymodules_path, **kwargs):
        return CaptureAnalysisResult(stats=[])

    monkeypatch.setattr(gsp, "analyze_capture", fake_analyze)
    _result, record = service.profile(project, "capture.rdc", "pymodules")

    assert service.history(project.id) == [record]


# --- CLI ---------------------------------------------------------------


def test_cli_prints_summary(monkeypatch, capsys):
    def fake_analyze(rdc_path, pymodules_path, **kwargs):
        return CaptureAnalysisResult(stats=[])

    monkeypatch.setattr(gsp, "analyze_capture", fake_analyze)
    exit_code = gsp._cli(["capture.rdc", "pymodules"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No shaders found" in out


def test_cli_json_flag(monkeypatch, capsys):
    def fake_analyze(rdc_path, pymodules_path, **kwargs):
        return CaptureAnalysisResult(
            stats=[
                ShaderGpuStats("A", gpu_time_ms=0.1, texture_bandwidth_bytes=0, draw_call_count=1)
            ]
        )

    monkeypatch.setattr(gsp, "analyze_capture", fake_analyze)
    exit_code = gsp._cli(["capture.rdc", "pymodules", "--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert exit_code == 0
    assert parsed["feature_id"] == gsp.FEATURE_ID


def test_cli_reports_capture_error(monkeypatch, capsys):
    def fake_analyze(rdc_path, pymodules_path, **kwargs):
        return CaptureAnalysisResult(error="RenderDoc isn't installed.", renderdoc_unavailable=True)

    monkeypatch.setattr(gsp, "analyze_capture", fake_analyze)
    exit_code = gsp._cli(["capture.rdc", "pymodules"])

    assert exit_code == 1
