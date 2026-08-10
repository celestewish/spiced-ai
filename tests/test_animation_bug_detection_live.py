"""Tests for automation.animation_bug_detection_live (Implementation Bible,
Feature 11). ``analyze_playtest_capture``/``build_finding`` run for real
against synthetic PlaytestCaptureResult data (no mocking needed -- pure
analysis); the Unity subprocess call itself
(``connectors.unity_playtest_capture.run_playtest_capture``) is
monkeypatched at the module boundary, matching this codebase's existing
convention for every other Unity-backed feature (see
tests/test_state_machine_validation.py)."""

from __future__ import annotations

import pytest

from spiced.automation import animation_bug_detection_live as abl
from spiced.automation.finding import STATUS_ERROR, STATUS_FLAGGED, STATUS_PASS, Finding
from spiced.automation.motion_quality import FootSlideEvent
from spiced.connectors.unity_playtest_capture import PlaytestCaptureResult, PlaytestFrame
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

FPS = 30.0


def _frame(i, state, root_x, foot_positions, bone_rotations):
    return PlaytestFrame(
        time_s=i / FPS,
        state_name=state,
        root_position=(root_x, 0.0, 0.0),
        foot_positions=foot_positions,
        bone_rotations_euler=bone_rotations,
    )


def _clean_capture() -> PlaytestCaptureResult:
    """A short walk cycle with no bugs: the foot plants and stays put while
    grounded, bones move smoothly, no reversion to bind pose."""
    bind_pose = {"Spine": (0.0, 0.0, 0.0), "LeftUpperArm": (0.0, 0.0, 0.0)}
    frames = []
    for i in range(12):
        # Foot planted at a fixed spot while grounded (y=0.0), root advances.
        # (i + 1) * a large-enough step so frame 0 is never within the
        # tpose epsilon of the (0, 0, 0) bind pose -- a real walk cycle
        # doesn't rest in bind pose at frame 0.
        frames.append(
            _frame(
                i, "Walk", root_x=i * 0.1,
                foot_positions={"LeftFoot": (1.0, 0.0, 0.0)},
                bone_rotations={
                    "Spine": ((i + 1) * 10.0, 0.0, 0.0),
                    "LeftUpperArm": ((i + 1) * 6.0, 0.0, 0.0),
                },
            )
        )
    return PlaytestCaptureResult(frames=frames, bind_pose_rotations=bind_pose)


# --- analyze_playtest_capture: foot sliding -----------------------------


def test_analyze_clean_capture_flags_nothing():
    result = _clean_capture()
    analysis = abl.analyze_playtest_capture(result, foot_bone_names=["LeftFoot"])
    assert analysis.foot_sliding_events == []
    assert analysis.tpose_frames == []
    assert analysis.snap_transitions == []


def test_analyze_detects_foot_sliding():
    bind_pose = {"Spine": (0.0, 0.0, 0.0)}
    frames = []
    for i in range(12):
        # Foot is grounded but keeps moving with the root -- dragging.
        frames.append(
            _frame(
                i, "Walk", root_x=i * 0.3,
                foot_positions={"LeftFoot": (i * 0.3, 0.0, 0.0)},
                bone_rotations={"Spine": (i * 1.0, 0.0, 0.0)},
            )
        )
    result = PlaytestCaptureResult(frames=frames, bind_pose_rotations=bind_pose)

    analysis = abl.analyze_playtest_capture(
        result, foot_bone_names=["LeftFoot"], slide_speed_threshold=0.1
    )

    assert len(analysis.foot_sliding_events) == 1
    assert analysis.foot_sliding_events[0].joint == "LeftFoot"


def test_analyze_capture_with_all_three_defects_catches_all_with_correct_timestamps():
    """Bible acceptance criteria: one recording with a deliberately induced
    foot-slide, a deliberately zeroed bone pose mid-clip, and a
    deliberately instantaneous transition all in the same capture -- all
    three must be caught, each with the right frame/time/bone/state."""
    bind_pose = {"Spine": (0.0, 0.0, 0.0)}
    frames = []
    for i in range(12):
        # Foot sliding: grounded but dragged along with the root the whole
        # time (frames 0-11).
        foot = {"LeftFoot": (i * 0.3, 0.0, 0.0)}
        if i == 6:
            # Deliberately zeroed mid-clip -- a T-pose frame.
            spine = (0.0, 0.0, 0.0)
        elif i >= 8:
            # Instant snap right at the Walk -> Jump transition (frame 8).
            spine = (170.0 + (i - 8) * 2.0, 0.0, 0.0)
        else:
            # (i + 1) so frame 0 is never coincidentally within the tpose
            # epsilon of the (0, 0, 0) bind pose.
            spine = ((i + 1) * 5.0, 0.0, 0.0)
        state = "Walk" if i < 8 else "Jump"
        frames.append(_frame(i, state, root_x=0.0, foot_positions=foot,
                              bone_rotations={"Spine": spine}))
    result = PlaytestCaptureResult(frames=frames, bind_pose_rotations=bind_pose)

    analysis = abl.analyze_playtest_capture(
        result, foot_bone_names=["LeftFoot"], slide_speed_threshold=0.1,
        snap_threshold_deg_s=500.0,
    )

    assert len(analysis.foot_sliding_events) == 1
    assert analysis.foot_sliding_events[0].joint == "LeftFoot"

    assert len(analysis.tpose_frames) == 1
    assert analysis.tpose_frames[0].frame == 6
    assert analysis.tpose_frames[0].time_s == pytest.approx(6 / FPS)

    assert len(analysis.snap_transitions) == 1
    assert analysis.snap_transitions[0].frame == 8
    assert analysis.snap_transitions[0].bone == "Spine"
    assert analysis.snap_transitions[0].from_state == "Walk"
    assert analysis.snap_transitions[0].to_state == "Jump"
    assert analysis.snap_transitions[0].time_s == pytest.approx(8 / FPS)


# --- detect_tpose_frames ------------------------------------------------


def test_detect_tpose_frames_flags_mid_clip_reversion():
    bind_pose = {"Spine": (0.0, 0.0, 0.0), "LeftUpperArm": (0.0, 0.0, 0.0)}
    frames = []
    for i in range(10):
        if i == 5:
            # Deliberately zeroed mid-clip -- matches the bind pose exactly.
            rot = {"Spine": (0.0, 0.0, 0.0), "LeftUpperArm": (0.0, 0.0, 0.0)}
        else:
            rot = {"Spine": ((i + 1) * 5.0, 0.0, 0.0), "LeftUpperArm": ((i + 1) * 3.0, 0.0, 0.0)}
        frames.append(_frame(i, "Walk", root_x=0.0, foot_positions={}, bone_rotations=rot))
    result = PlaytestCaptureResult(frames=frames, bind_pose_rotations=bind_pose)

    events = abl.detect_tpose_frames(result.frames, result.bind_pose_rotations)

    assert len(events) == 1
    assert events[0].frame == 5


def test_detect_tpose_frames_no_bind_pose_flags_nothing():
    frames = [_frame(0, "Walk", 0.0, {}, {"Spine": (0.0, 0.0, 0.0)})]
    assert abl.detect_tpose_frames(frames, {}) == []


# --- detect_snap_transitions ---------------------------------------------


def test_detect_snap_transitions_flags_instant_change_at_state_boundary():
    frames = [
        _frame(0, "Idle", 0.0, {}, {"Spine": (0.0, 0.0, 0.0)}),
        _frame(1, "Idle", 0.0, {}, {"Spine": (2.0, 0.0, 0.0)}),
        # State changes Idle -> Jump right as Spine snaps hard.
        _frame(2, "Jump", 0.0, {}, {"Spine": (170.0, 0.0, 0.0)}),
        _frame(3, "Jump", 0.0, {}, {"Spine": (172.0, 0.0, 0.0)}),
    ]
    events = abl.detect_snap_transitions(frames, threshold_deg_s=500.0)

    assert len(events) == 1
    assert events[0].bone == "Spine"
    assert events[0].from_state == "Idle"
    assert events[0].to_state == "Jump"


def test_detect_snap_transitions_ignores_fast_movement_mid_state():
    # Same instantaneous jump in rotation, but no state change at that
    # frame -- a fast movement mid-clip, not a transition snap.
    frames = [
        _frame(0, "Jump", 0.0, {}, {"Spine": (0.0, 0.0, 0.0)}),
        _frame(1, "Jump", 0.0, {}, {"Spine": (2.0, 0.0, 0.0)}),
        _frame(2, "Jump", 0.0, {}, {"Spine": (170.0, 0.0, 0.0)}),
        _frame(3, "Jump", 0.0, {}, {"Spine": (172.0, 0.0, 0.0)}),
    ]
    events = abl.detect_snap_transitions(frames, threshold_deg_s=500.0)
    assert events == []


# --- build_finding / run_live_animation_bug_detection ---------------------


def test_build_finding_status_pass_when_clean():
    analysis = abl.LivePlaytestAnalysis()
    finding = abl.build_finding(analysis, "1")
    assert finding.status == STATUS_PASS
    assert finding.items == []


def test_build_finding_status_flagged_with_all_three_bug_types():
    analysis = abl.LivePlaytestAnalysis(
        foot_sliding_events=[
            FootSlideEvent("LeftFoot", 1, 5, 0.03, 0.16, 0.5)
        ],
        tpose_frames=[abl.TposeFrameEvent(frame=5, time_s=0.16, state_name="Walk",
                                           matched_bone_fraction=1.0)],
        snap_transitions=[
            abl.SnapTransitionEvent(bone="Spine", frame=2, time_s=0.06,
                                     angular_speed_deg_s=900.0, from_state="Idle",
                                     to_state="Jump")
        ],
    )
    finding = abl.build_finding(analysis, "1")
    assert finding.status == STATUS_FLAGGED
    issue_types = {i.detail["issue_type"] for i in finding.items}
    assert issue_types == {"foot_sliding", "tpose_frame", "snap_transition"}


def test_run_live_animation_bug_detection_end_to_end_clean(monkeypatch):
    def fake_run_playtest_capture(unity_path, project_path, request, timeout_s=600):
        return _clean_capture()

    monkeypatch.setattr(abl, "run_playtest_capture", fake_run_playtest_capture)

    finding = abl.run_live_animation_bug_detection(
        "unity", "/proj", "1", scene_path="Assets/Main.unity", marker_name="Player",
        foot_bone_names=["LeftFoot"], tracked_bone_names=["Spine", "LeftUpperArm"],
        state_names=["Walk"],
    )
    assert finding.status == STATUS_PASS


def test_run_live_animation_bug_detection_reports_capture_error(monkeypatch):
    def fake_run_playtest_capture(unity_path, project_path, request, timeout_s=600):
        return PlaytestCaptureResult(error="Unity did not finish within 10 minutes")

    monkeypatch.setattr(abl, "run_playtest_capture", fake_run_playtest_capture)

    finding = abl.run_live_animation_bug_detection(
        "unity", "/proj", "1", scene_path="Assets/Main.unity", marker_name="Player",
        foot_bone_names=["LeftFoot"], tracked_bone_names=["Spine"], state_names=["Walk"],
    )
    assert finding.status == STATUS_ERROR
    assert "10 minutes" in finding.summary


def test_run_live_animation_bug_detection_no_states_is_error(tmp_path):
    finding = abl.run_live_animation_bug_detection(
        "unity", str(tmp_path), "1", scene_path="Assets/Main.unity", marker_name="Player",
        foot_bone_names=["LeftFoot"], tracked_bone_names=["Spine"], state_names=None,
    )
    assert finding.status == STATUS_ERROR


# --- infer_state_names ----------------------------------------------------


def test_infer_state_names_reads_real_controller_files(tmp_path):
    controller_text = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1102 &200
AnimatorState:
  m_Name: Idle
  m_Transitions: []
  m_Motion: {fileID: 7400000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
--- !u!1107 &400
AnimatorStateMachine:
  m_Name: Base Layer
  m_ChildStates:
  - m_State: {fileID: 200}
  m_ChildStateMachines: []
  m_AnyStateTransitions: []
  m_DefaultState: {fileID: 200}
"""
    controller_path = tmp_path / "Assets" / "Player.controller"
    controller_path.parent.mkdir(parents=True, exist_ok=True)
    controller_path.write_text(controller_text, encoding="utf-8")

    names = abl.infer_state_names(tmp_path)
    assert names == ["Idle"]


# --- LiveAnimationBugDetectionService --------------------------------------


def test_service_run_persists_finding(monkeypatch):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    service = abl.LiveAnimationBugDetectionService(findings)

    def fake_run(unity_path, project_path, project_id, **kwargs):
        return abl.build_finding(abl.LivePlaytestAnalysis(), project_id)

    monkeypatch.setattr(abl, "run_live_animation_bug_detection", fake_run)

    finding, record = service.run(
        project, "unity", scene_path="Assets/Main.unity", marker_name="Player",
        foot_bone_names=["LeftFoot"], tracked_bone_names=["Spine"],
    )
    assert record.feature_id == abl.FEATURE_ID
    assert findings.list_for_project(project.id) == [record]


def test_service_history_filters_by_feature_id():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    service = abl.LiveAnimationBugDetectionService(findings)
    findings.create(project.id, abl.build_finding(abl.LivePlaytestAnalysis(), str(project.id)))
    findings.create(
        project.id,
        Finding(feature_id="vfx.other", project_id=str(project.id), status=STATUS_PASS,
                summary="x"),
    )

    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].feature_id == abl.FEATURE_ID


# --- CLI --------------------------------------------------------------------


def test_cli_prints_summary_and_returns_zero_on_pass(monkeypatch, capsys):
    def fake_run(*args, **kwargs):
        return abl.build_finding(abl.LivePlaytestAnalysis(), "1")

    monkeypatch.setattr(abl, "run_live_animation_bug_detection", fake_run)
    exit_code = abl._cli([
        "unity", "/proj", "Assets/Main.unity", "Player",
        "--foot-bones", "LeftFoot", "--tracked-bones", "Spine",
    ])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Clean run" in out
