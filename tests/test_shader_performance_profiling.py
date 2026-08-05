"""Shader Performance Profiling: heuristic scoring + hardware-tier flagging."""

from __future__ import annotations

from spiced.core.shader_performance_profiling import (
    FRAGILE_HARDWARE_TIERS,
    HIGH_LINES_PER_PASS,
    NoUnityFolderError,
    ShaderPerformanceProfilingService,
    analyze_shader_text,
    scan_shaders,
)
from spiced.storage.database import Database
from spiced.storage.projects import Project, ProjectRepository
from spiced.storage.shader_profiling_reports import ShaderProfilingReportRepository

_SIMPLE_SHADER = """
Shader "Custom/Simple" {
    SubShader {
        Pass {
            sampler2D _MainTex;
            fixed4 col = tex2D(_MainTex, i.uv);
        }
    }
}
"""

_EXPENSIVE_SHADER = (
    "Shader \"Custom/Expensive\" {\n"
    "    SubShader {\n"
    "        Pass {\n"
    "            sampler2D _Tex1; sampler2D _Tex2; sampler2D _Tex3; sampler2D _Tex4;\n"
    "            for (int i = 0; i < 8; i++) {\n"
    + "                float x = i;\n" * (HIGH_LINES_PER_PASS + 5)
    + "            }\n"
    "        }\n"
    "        Pass { sampler2D _A; }\n"
    "        Pass { sampler2D _B; }\n"
    "    }\n"
    "}\n"
)


def test_simple_shader_is_not_flagged():
    result = analyze_shader_text(_SIMPLE_SHADER, "Assets/simple.shader")
    assert result.likely_expensive is False
    assert result.at_risk_tiers == []
    assert result.sampler_count == 1
    assert result.pass_count == 1


def test_expensive_shader_is_flagged_with_reasons_and_tiers():
    result = analyze_shader_text(_EXPENSIVE_SHADER, "Assets/expensive.shader")
    assert result.likely_expensive is True
    assert result.sampler_count >= 4
    assert result.pass_count >= 3
    assert result.loop_count >= 1
    assert result.max_lines_in_pass >= HIGH_LINES_PER_PASS
    assert result.reasons  # every trigger produces a human-readable reason
    assert set(result.at_risk_tiers) == set(FRAGILE_HARDWARE_TIERS)
    # The two flagged tiers should be the weakest (lowest fps_factor) ones.
    assert "Mid-range PC" not in result.at_risk_tiers


def test_scan_shaders_walks_assets_folder_and_detects_shadergraph(tmp_path):
    assets = tmp_path / "Assets"
    (assets / "Shaders").mkdir(parents=True)
    (assets / "Shaders" / "simple.shader").write_text(_SIMPLE_SHADER, encoding="utf-8")
    (assets / "Shaders" / "expensive.shader").write_text(_EXPENSIVE_SHADER, encoding="utf-8")
    (assets / "Shaders" / "graph.shadergraph").write_text('{"m_SGVersion": 3}', encoding="utf-8")

    result = scan_shaders(tmp_path)
    assert len(result.shaders) == 2
    assert result.flagged_count == 1
    assert len(result.shader_graphs) == 1
    assert result.shader_graphs[0].parses_as_json is True
    assert "not deeply analyzed" in result.shader_graphs[0].note


def test_scan_shaders_returns_empty_result_without_assets_folder(tmp_path):
    result = scan_shaders(tmp_path)
    assert result.shaders == []
    assert result.shader_graphs == []


def test_service_scan_persists_report(tmp_path):
    assets = tmp_path / "Assets"
    assets.mkdir()
    (assets / "a.shader").write_text(_SIMPLE_SHADER, encoding="utf-8")

    db = Database(":memory:")
    project = ProjectRepository(db).create("Demo", path=str(tmp_path))
    service = ShaderPerformanceProfilingService(ShaderProfilingReportRepository(db))

    result, report = service.scan(project)
    assert result.shaders[0].path == "Assets/a.shader"
    assert report.findings["shaders"][0]["path"] == "Assets/a.shader"

    history = service.history(project.id)
    assert len(history) == 1


def test_service_scan_requires_connected_folder():
    db = Database(":memory:")
    project = Project(
        id=1, name="No folder", engine="Unity", path=None, description=None, created_at="now"
    )
    service = ShaderPerformanceProfilingService(ShaderProfilingReportRepository(db))
    try:
        service.scan(project)
    except NoUnityFolderError:
        pass
    else:
        raise AssertionError("expected NoUnityFolderError")
