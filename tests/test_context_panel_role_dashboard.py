"""Role-Based Dashboards: the Context Panel's per-discipline summary text.

Tests the pure ``_role_summary_text`` helper directly (no Qt event loop
needed) for the 3-4 disciplines it covers: artist, audio, animation,
programmer.
"""

from __future__ import annotations

from spiced.app.services import Services
from spiced.storage.animation_state_machine_reports import AnimationStateMachineReportRepository
from spiced.storage.asset_review_reports import AssetReviewReportRepository
from spiced.storage.audio_checklist_reports import AudioChecklistReportRepository
from spiced.storage.code_health_reports import CodeHealthReportRepository
from spiced.ui.context_panel import _role_summary_text


def _setup_project(tmp_path):
    services = Services(":memory:")
    project = services.projects.create_project("Demo", path=str(tmp_path))
    return services, project


def test_artist_summary_counts_flagged_assets(tmp_path):
    services, project = _setup_project(tmp_path)
    AssetReviewReportRepository(services.db).create(
        project.id,
        [
            {"path": "a.png", "passed": True, "issues": []},
            {"path": "b.png", "passed": False, "issues": ["oversized"]},
        ],
    )
    text = _role_summary_text(services, project, "artist")
    assert "1 asset(s) flagged" in text


def test_artist_summary_with_no_saved_runs(tmp_path):
    services, project = _setup_project(tmp_path)
    text = _role_summary_text(services, project, "artist")
    assert "no saved runs yet" in text


def test_audio_summary_counts_gaps(tmp_path):
    services, project = _setup_project(tmp_path)
    AudioChecklistReportRepository(services.db).create(
        project.id,
        {
            "scripts_scanned": 3,
            "audio_files_found": 2,
            "matched_references": [],
            "unmatched_references": [{"file": "a.cs", "line": 1}],
            "unreferenced_audio_files": ["b.wav"],
        },
    )
    text = _role_summary_text(services, project, "audio")
    assert "2 gap(s)" in text


def test_animation_summary_counts_flagged_issues(tmp_path):
    services, project = _setup_project(tmp_path)
    AnimationStateMachineReportRepository(services.db).create(
        project.id,
        {
            "controllers_scanned": 1,
            "unreachable_states": [{"controller_file": "a", "state_name": "s"}],
            "missing_targets": [],
        },
    )
    text = _role_summary_text(services, project, "animation")
    assert "1 issue(s)" in text


def test_programmer_summary_reports_long_functions_and_todos(tmp_path):
    services, project = _setup_project(tmp_path)
    CodeHealthReportRepository(services.db).create(
        project.id,
        metrics={
            "line_count": 100,
            "function_count": 3,
            "longest_functions": [{"name": "Foo", "start_line": 1, "length": 55}],
            "todo_count": 2,
        },
    )
    text = _role_summary_text(services, project, "programmer")
    assert "1 long function(s)" in text
    assert "2 TODO(s)" in text


def test_unknown_discipline_returns_none(tmp_path):
    services, project = _setup_project(tmp_path)
    assert _role_summary_text(services, project, "design") is None
    assert _role_summary_text(services, project, "totally-made-up") is None
