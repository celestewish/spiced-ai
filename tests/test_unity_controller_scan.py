"""Tests for connectors.unity_controller_scan.

The base sample text below is a trimmed, faithful reproduction of a real
Unity-generated .controller file (fetched from a public GitHub repo during
development to verify field names/layout -- see the module's docstring) so
these tests exercise the parser against realistic structure, not a
convenient fiction.
"""

from __future__ import annotations

from spiced.connectors.unity_controller_scan import parse_controller_text, scan_controllers

# A trimmed, faithful reproduction of a real two-state Animator Controller
# (Empty --[OpenChest]--> OpenChest), verified against a real sample.
CHEST_CONTROLLER_TEXT = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1101 &-6720969233391456867
AnimatorStateTransition:
  m_ObjectHideFlags: 1
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_Name:
  m_Conditions:
  - m_ConditionMode: 1
    m_ConditionEvent: OpenChest
    m_EventTreshold: 0
  m_DstStateMachine: {fileID: 0}
  m_DstState: {fileID: 8859083180952537706}
  m_Solo: 0
  m_Mute: 0
  m_IsExit: 0
  serializedVersion: 3
  m_TransitionDuration: 0
  m_TransitionOffset: 0
  m_ExitTime: 0.75
  m_HasExitTime: 0
  m_HasFixedDuration: 1
  m_InterruptionSource: 0
  m_OrderedInterruption: 1
  m_CanTransitionToSelf: 1
--- !u!91 &9100000
AnimatorController:
  m_ObjectHideFlags: 0
  m_Name: Chest
  serializedVersion: 5
  m_AnimatorLayers:
  - serializedVersion: 5
    m_Name: Base Layer
    m_StateMachine: {fileID: 4811583679318663443}
--- !u!1102 &2228359611378032841
AnimatorState:
  serializedVersion: 5
  m_ObjectHideFlags: 1
  m_Name: Empty
  m_Speed: 1
  m_CycleOffset: 0
  m_Transitions:
  - {fileID: -6720969233391456867}
  m_StateMachineBehaviours: []
  m_Position: {x: 50, y: 50, z: 0}
  m_Motion: {fileID: 0}
  m_Tag:
--- !u!1107 &4811583679318663443
AnimatorStateMachine:
  serializedVersion: 5
  m_ObjectHideFlags: 1
  m_Name: Base Layer
  m_ChildStates:
  - serializedVersion: 1
    m_State: {fileID: 8859083180952537706}
    m_Position: {x: 290, y: 210, z: 0}
  - serializedVersion: 1
    m_State: {fileID: 2228359611378032841}
    m_Position: {x: 30, y: 210, z: 0}
  m_ChildStateMachines: []
  m_AnyStateTransitions: []
  m_EntryTransitions: []
  m_StateMachineTransitions: {}
  m_StateMachineBehaviours: []
  m_DefaultState: {fileID: 2228359611378032841}
--- !u!1102 &8859083180952537706
AnimatorState:
  serializedVersion: 5
  m_ObjectHideFlags: 1
  m_Name: OpenChest
  m_Speed: 1
  m_CycleOffset: 0
  m_Transitions: []
  m_StateMachineBehaviours: []
  m_Position: {x: 50, y: 50, z: 0}
  m_Motion: {fileID: 7400000, guid: 5d956dad69a1d024699cbdedb00f293e, type: 2}
  m_Tag:
"""


def test_parses_states_with_names_and_motion():
    controller = parse_controller_text(CHEST_CONTROLLER_TEXT, "Assets/Chest.controller")
    empty = controller.states["2228359611378032841"]
    open_chest = controller.states["8859083180952537706"]
    assert empty.name == "Empty"
    assert empty.has_motion is False
    assert open_chest.name == "OpenChest"
    assert open_chest.has_motion is True


def test_parses_state_transitions_list():
    controller = parse_controller_text(CHEST_CONTROLLER_TEXT, "Assets/Chest.controller")
    empty = controller.states["2228359611378032841"]
    assert empty.transition_ids == ["-6720969233391456867"]


def test_parses_state_machine_default_and_children():
    controller = parse_controller_text(CHEST_CONTROLLER_TEXT, "Assets/Chest.controller")
    sm = controller.state_machines["4811583679318663443"]
    assert sm.default_state_id == "2228359611378032841"
    assert set(sm.child_state_ids) == {"8859083180952537706", "2228359611378032841"}
    assert sm.child_state_machine_ids == []


def test_parses_transition_fields():
    controller = parse_controller_text(CHEST_CONTROLLER_TEXT, "Assets/Chest.controller")
    t = controller.transitions["-6720969233391456867"]
    assert t.kind == "AnimatorStateTransition"
    assert t.dst_state_id == "8859083180952537706"
    assert t.transition_duration == 0.0
    assert t.has_exit_time is False
    assert t.is_exit is False


def test_ignores_non_animation_documents():
    controller = parse_controller_text(CHEST_CONTROLLER_TEXT, "Assets/Chest.controller")
    # AnimatorController (class 91) isn't a state/state machine/transition.
    assert "9100000" not in controller.states
    assert "9100000" not in controller.state_machines
    assert "9100000" not in controller.transitions


def test_scan_controllers_finds_files_under_assets(tmp_path):
    controller_path = tmp_path / "Assets" / "Animations" / "Chest.controller"
    controller_path.parent.mkdir(parents=True, exist_ok=True)
    controller_path.write_text(CHEST_CONTROLLER_TEXT, encoding="utf-8")

    results = scan_controllers(tmp_path)
    assert len(results) == 1
    assert results[0].path == "Assets/Animations/Chest.controller"
    assert len(results[0].states) == 2


def test_scan_controllers_empty_project_returns_empty_list(tmp_path):
    assert scan_controllers(tmp_path) == []
