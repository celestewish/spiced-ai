"""Tests for core.animation_bug_detection: empty-state / zero-duration-transition
risk indicators, built from small synthetic .controller files under tmp_path."""

from __future__ import annotations

from spiced.core.animation_bug_detection import detect_animation_bugs

_CONTROLLER_WITH_EMPTY_STATE_AND_SNAP_TRANSITION = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1101 &100
AnimatorStateTransition:
  m_Name:
  m_DstStateMachine: {fileID: 0}
  m_DstState: {fileID: 300}
  m_IsExit: 0
  m_TransitionDuration: 0
  m_HasExitTime: 0
--- !u!1102 &200
AnimatorState:
  m_Name: Idle
  m_Transitions:
  - {fileID: 100}
  m_Motion: {fileID: 0}
--- !u!1102 &300
AnimatorState:
  m_Name: Walk
  m_Transitions: []
  m_Motion: {fileID: 7400000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
--- !u!1107 &400
AnimatorStateMachine:
  m_Name: Base Layer
  m_ChildStates:
  - m_State: {fileID: 200}
  - m_State: {fileID: 300}
  m_ChildStateMachines: []
  m_AnyStateTransitions: []
  m_DefaultState: {fileID: 200}
"""

_CONTROLLER_WITH_NORMAL_TRANSITION = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1101 &100
AnimatorStateTransition:
  m_Name:
  m_DstStateMachine: {fileID: 0}
  m_DstState: {fileID: 300}
  m_IsExit: 0
  m_TransitionDuration: 0.25
  m_HasExitTime: 0
--- !u!1102 &200
AnimatorState:
  m_Name: Idle
  m_Transitions:
  - {fileID: 100}
  m_Motion: {fileID: 7400000, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 2}
--- !u!1102 &300
AnimatorState:
  m_Name: Walk
  m_Transitions: []
  m_Motion: {fileID: 7400000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
--- !u!1107 &400
AnimatorStateMachine:
  m_Name: Base Layer
  m_ChildStates:
  - m_State: {fileID: 200}
  - m_State: {fileID: 300}
  m_ChildStateMachines: []
  m_AnyStateTransitions: []
  m_DefaultState: {fileID: 200}
"""


def _write_controller(tmp_path, text, name="Player.controller"):
    path = tmp_path / "Assets" / "Animations" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_flags_empty_state_with_no_motion(tmp_path):
    _write_controller(tmp_path, _CONTROLLER_WITH_EMPTY_STATE_AND_SNAP_TRANSITION)
    result = detect_animation_bugs(tmp_path)
    names = {f.state_name for f in result.empty_states}
    assert "Idle" in names
    assert "Walk" not in names


def test_flags_zero_duration_non_exit_transition(tmp_path):
    _write_controller(tmp_path, _CONTROLLER_WITH_EMPTY_STATE_AND_SNAP_TRANSITION)
    result = detect_animation_bugs(tmp_path)
    assert len(result.zero_duration_transitions) == 1
    finding = result.zero_duration_transitions[0]
    assert finding.from_state_name == "Idle"
    assert finding.to_state_name == "Walk"


def test_does_not_flag_nonzero_duration_transition(tmp_path):
    _write_controller(tmp_path, _CONTROLLER_WITH_NORMAL_TRANSITION)
    result = detect_animation_bugs(tmp_path)
    assert result.zero_duration_transitions == []


def test_does_not_flag_state_with_motion_assigned(tmp_path):
    _write_controller(tmp_path, _CONTROLLER_WITH_NORMAL_TRANSITION)
    result = detect_animation_bugs(tmp_path)
    assert result.empty_states == []


def test_result_reports_controllers_scanned_count(tmp_path):
    _write_controller(tmp_path, _CONTROLLER_WITH_NORMAL_TRANSITION, "A.controller")
    _write_controller(tmp_path, _CONTROLLER_WITH_EMPTY_STATE_AND_SNAP_TRANSITION, "B.controller")
    result = detect_animation_bugs(tmp_path)
    assert result.controllers_scanned == 2


def test_empty_project_returns_no_findings(tmp_path):
    result = detect_animation_bugs(tmp_path)
    assert result.empty_states == []
    assert result.zero_duration_transitions == []
    assert result.controllers_scanned == 0


def test_caveat_mentions_risk_indicator_not_confirmed_bug(tmp_path):
    result = detect_animation_bugs(tmp_path)
    assert "risk indicator" in result.caveat.lower()
    assert "not confirmed" in result.caveat.lower() or "never" in result.caveat.lower()
