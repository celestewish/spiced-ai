"""Tests for core.animation_state_machine_check: unreachable-state and
missing-target-state detection, built from small synthetic .controller files."""

from __future__ import annotations

import pytest

from spiced.core.animation_state_machine_check import (
    AnimationStateMachineCheckService,
    NoUnityFolderError,
    scan_state_machines,
)
from spiced.storage.animation_state_machine_reports import AnimationStateMachineReportRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

# Idle (default) -> Walk (reachable). Jump has no incoming transition and
# isn't the default -> unreachable.
_CONTROLLER_WITH_UNREACHABLE_STATE = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1101 &100
AnimatorStateTransition:
  m_Name:
  m_DstStateMachine: {fileID: 0}
  m_DstState: {fileID: 300}
  m_IsExit: 0
  m_TransitionDuration: 0.1
--- !u!1102 &200
AnimatorState:
  m_Name: Idle
  m_Transitions:
  - {fileID: 100}
  m_Motion: {fileID: 7400000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
--- !u!1102 &300
AnimatorState:
  m_Name: Walk
  m_Transitions: []
  m_Motion: {fileID: 7400000, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 2}
--- !u!1102 &500
AnimatorState:
  m_Name: Jump
  m_Transitions: []
  m_Motion: {fileID: 7400000, guid: cccccccccccccccccccccccccccccccc, type: 2}
--- !u!1107 &400
AnimatorStateMachine:
  m_Name: Base Layer
  m_ChildStates:
  - m_State: {fileID: 200}
  - m_State: {fileID: 300}
  - m_State: {fileID: 500}
  m_ChildStateMachines: []
  m_AnyStateTransitions: []
  m_DefaultState: {fileID: 200}
"""

# A transition pointing at a state fileID that doesn't exist anywhere in the
# file (600) -- simulates a hand-edited/corrupted controller.
_CONTROLLER_WITH_MISSING_TARGET = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1101 &100
AnimatorStateTransition:
  m_Name:
  m_DstStateMachine: {fileID: 0}
  m_DstState: {fileID: 600}
  m_IsExit: 0
  m_TransitionDuration: 0.1
--- !u!1102 &200
AnimatorState:
  m_Name: Idle
  m_Transitions:
  - {fileID: 100}
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

# Every state is reachable: default + one transition.
_CONTROLLER_ALL_REACHABLE = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1101 &100
AnimatorStateTransition:
  m_Name:
  m_DstStateMachine: {fileID: 0}
  m_DstState: {fileID: 300}
  m_IsExit: 0
  m_TransitionDuration: 0.1
--- !u!1102 &200
AnimatorState:
  m_Name: Idle
  m_Transitions:
  - {fileID: 100}
  m_Motion: {fileID: 7400000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 2}
--- !u!1102 &300
AnimatorState:
  m_Name: Walk
  m_Transitions: []
  m_Motion: {fileID: 7400000, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 2}
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


def test_flags_unreachable_state(tmp_path):
    _write_controller(tmp_path, _CONTROLLER_WITH_UNREACHABLE_STATE)
    result = scan_state_machines(tmp_path)
    names = {f.state_name for f in result.unreachable_states}
    assert names == {"Jump"}


def test_does_not_flag_reachable_states(tmp_path):
    _write_controller(tmp_path, _CONTROLLER_ALL_REACHABLE)
    result = scan_state_machines(tmp_path)
    assert result.unreachable_states == []


def test_flags_missing_transition_target(tmp_path):
    _write_controller(tmp_path, _CONTROLLER_WITH_MISSING_TARGET)
    result = scan_state_machines(tmp_path)
    assert len(result.missing_targets) == 1
    finding = result.missing_targets[0]
    assert finding.missing_kind == "state"
    assert finding.missing_file_id == "600"


def test_does_not_flag_valid_transition_target(tmp_path):
    _write_controller(tmp_path, _CONTROLLER_ALL_REACHABLE)
    result = scan_state_machines(tmp_path)
    assert result.missing_targets == []


def test_empty_project_returns_no_findings(tmp_path):
    result = scan_state_machines(tmp_path)
    assert result.unreachable_states == []
    assert result.missing_targets == []
    assert result.controllers_scanned == 0


def test_service_scan_raises_without_project_path():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = AnimationStateMachineCheckService(AnimationStateMachineReportRepository(db))
    with pytest.raises(NoUnityFolderError):
        service.scan(project)


def test_service_scan_saves_a_report(tmp_path):
    _write_controller(tmp_path, _CONTROLLER_WITH_UNREACHABLE_STATE)
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")
    service = AnimationStateMachineCheckService(AnimationStateMachineReportRepository(db))

    result, report = service.scan(project)
    assert len(result.unreachable_states) == 1
    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].id == report.id
    assert history[0].findings["controllers_scanned"] == 1
