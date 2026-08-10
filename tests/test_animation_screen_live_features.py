"""Offscreen Qt smoke tests for the Animation screen's two new Phase 2
sections (Implementation Bible, Features 11 & 12) -- exercises the wiring
methods directly with real result objects, the same convention as this
app's other screen tests (see tests/test_diff_viewer_consumers.py)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.automation.animation_bug_detection_live import (  # noqa: E402
    LivePlaytestAnalysis,
    SnapTransitionEvent,
    TposeFrameEvent,
    build_finding,
)
from spiced.automation.mocap_cleanup_assist import MocapCleanupAnalysis  # noqa: E402
from spiced.automation.mocap_cleanup_assist import (
    build_finding as build_mocap_finding,  # noqa: E402
)
from spiced.automation.motion_quality import FootSlideEvent, JitterEvent  # noqa: E402
from spiced.ui.screens.animation import AnimationScreen, _split_names  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


# --- _split_names -------------------------------------------------------


def test_split_names_trims_and_drops_blanks():
    assert _split_names(" LeftFoot, RightFoot ,, Spine") == ["LeftFoot", "RightFoot", "Spine"]
    assert _split_names("") == []


# --- Animation Bug Detection, Live Capture (Feature 11) ---------------------


def test_live_bug_detection_section_constructs_with_placeholders(tmp_path):
    screen = AnimationScreen(_services(tmp_path))
    assert screen._live_run_btn.isEnabled() is True
    assert screen._live_result.toPlainText() == ""


def test_live_bug_detection_on_done_renders_plain_language_not_json(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = AnimationScreen(services)

    analysis = LivePlaytestAnalysis(
        foot_sliding_events=[FootSlideEvent("LeftFoot", 1, 5, 0.03, 0.16, 0.5)],
        tpose_frames=[TposeFrameEvent(frame=5, time_s=0.16, state_name="Walk",
                                       matched_bone_fraction=1.0)],
        snap_transitions=[
            SnapTransitionEvent(bone="Spine", frame=2, time_s=0.06, angular_speed_deg_s=900.0,
                                 from_state="Idle", to_state="Jump")
        ],
    )
    finding = build_finding(analysis, str(project.id))

    screen._on_live_run_done(finding)

    text = screen._live_result.toPlainText()
    assert "{" not in text  # not raw JSON
    assert "LeftFoot" in text
    assert "Spine" in text
    assert finding.summary in text


def test_live_bug_detection_history_refreshes_after_done(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = AnimationScreen(services)

    finding = build_finding(LivePlaytestAnalysis(), str(project.id))
    services.live_animation_bug_detection._findings.create(project.id, finding)

    screen._refresh_live_history()
    assert "No runs saved yet." not in screen._live_history.toPlainText()


def test_live_bug_detection_history_before_project_selected(tmp_path):
    screen = AnimationScreen(_services(tmp_path))
    screen._refresh_live_history()
    assert "active project" in screen._live_history.toPlainText()


# --- Mocap Cleanup Assist (Feature 12) --------------------------------------


def test_mocap_cleanup_section_constructs_with_placeholders(tmp_path):
    screen = AnimationScreen(_services(tmp_path))
    assert screen._mocap_run_btn.isEnabled() is True
    assert screen._mocap_result.toPlainText() == ""


def test_mocap_cleanup_on_done_renders_plain_language_not_json(tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = AnimationScreen(services)

    analysis = MocapCleanupAnalysis(
        foot_sliding_events=[FootSlideEvent("LeftFoot", 1, 5, 0.03, 0.16, 0.5)],
        jitter_frames=[JitterEvent("Spine", 12, 0.4, 42.0)],
    )
    finding = build_mocap_finding(analysis, str(project.id), "take01.bvh")

    screen._on_mocap_done(finding)

    text = screen._mocap_result.toPlainText()
    assert "{" not in text
    assert "LeftFoot" in text
    assert "Spine" in text


def test_mocap_cleanup_browse_and_run_require_a_file(tmp_path, monkeypatch):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    services.set_active_project(project.id)
    screen = AnimationScreen(services)

    shown = []
    monkeypatch.setattr(
        "spiced.ui.screens.animation.QMessageBox.information",
        lambda *a, **k: shown.append(True),
    )
    screen._mocap_file_input.setText("")
    screen._on_mocap_run()
    assert shown == [True]
