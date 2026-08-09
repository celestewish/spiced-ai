"""Tests for automation.state_machine_validation (Implementation Bible,
Feature 7). State-machine checks run for real against small synthetic
.controller files (same verified format as
tests/test_animation_state_machine_check.py); the retarget check's Unity
call is monkeypatched -- no real Unity install is required."""

from __future__ import annotations

import json

from spiced.automation import state_machine_validation as smv
from spiced.automation.finding import STATUS_FLAGGED, STATUS_PASS
from spiced.connectors.unity_skeleton_export import SkeletonExportOutcome, SkeletonExportRunResult
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

# Idle (default) -> Walk (reachable, has no outgoing transitions of its own
# -> dead end). Jump has no incoming transition and isn't the default ->
# unreachable, and also has no outgoing transitions -> also a dead end.
_CONTROLLER = """%YAML 1.1
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


def _write_controller(project_root, rel_path, text):
    path = project_root / "Assets" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- find_dead_end_states / check_state_machines ----------------------------


def test_check_state_machines_catches_unreachable_and_dead_end(tmp_path):
    _write_controller(tmp_path, "Player.controller", _CONTROLLER)

    items = smv.check_state_machines(tmp_path)

    issue_types = [(i.detail.get("issue_type"), i.message) for i in items]
    unreachable = [m for t, m in issue_types if t == "unreachable_state"]
    dead_ends = [m for t, m in issue_types if t == "dead_end_state"]

    assert any("Jump" in m for m in unreachable)
    # Walk is reachable (Idle -> Walk) but has zero outgoing transitions.
    assert any("Walk" in m for m in dead_ends)
    # Jump is both unreachable and a dead end.
    assert any("Jump" in m for m in dead_ends)


def test_check_state_machines_no_controllers_no_issues(tmp_path):
    (tmp_path / "Assets").mkdir()
    assert smv.check_state_machines(tmp_path) == []


# --- normalize_bone_name / diff_skeletons -----------------------------------


def test_normalize_bone_name_strips_known_prefix():
    assert smv.normalize_bone_name("mixamorig:Hips") == "hips"
    assert smv.normalize_bone_name("Hips") == "hips"


def test_normalize_bone_name_custom_prefix():
    assert smv.normalize_bone_name("rig:Spine", alias_prefixes=("rig:",)) == "spine"


def test_diff_skeletons_exact_match_no_unmapped():
    source = ["Hips", "Spine", "Head"]
    target = ["Hips", "Spine", "Head"]
    assert smv.diff_skeletons(source, target) == []


def test_diff_skeletons_alias_prefix_match_no_unmapped():
    source = ["mixamorig:Hips", "mixamorig:Spine"]
    target = ["Hips", "Spine"]
    assert smv.diff_skeletons(source, target) == []


def test_diff_skeletons_three_unmapped_bones_all_surface():
    source = ["Hips", "Spine", "Head", "LeftHandThumb1", "RightHandThumb1", "Tail"]
    target = ["Hips", "Spine", "Head"]
    unmapped = smv.diff_skeletons(source, target)
    assert set(unmapped) == {"LeftHandThumb1", "RightHandThumb1", "Tail"}


# --- check_retarget -------------------------------------------------------


def test_check_retarget_flags_unmapped_bones(tmp_path, monkeypatch):
    def fake_run_export(unity_path, project_path, model_paths, timeout_s=600):
        return SkeletonExportRunResult(
            outcomes=[
                SkeletonExportOutcome(
                    model_path="Assets/Source.fbx",
                    succeeded=True,
                    bone_names=["Hips", "Spine", "Tail"],
                ),
                SkeletonExportOutcome(
                    model_path="Assets/Target.fbx", succeeded=True, bone_names=["Hips", "Spine"]
                ),
            ]
        )

    monkeypatch.setattr(smv, "run_export", fake_run_export)

    items = smv.check_retarget(
        "Unity.exe", tmp_path, "Assets/Source.fbx", "Assets/Target.fbx"
    )

    assert len(items) == 1
    assert items[0].severity == "warning"
    assert items[0].detail["bone_name"] == "Tail"


def test_check_retarget_all_mapped_is_info(tmp_path, monkeypatch):
    def fake_run_export(unity_path, project_path, model_paths, timeout_s=600):
        return SkeletonExportRunResult(
            outcomes=[
                SkeletonExportOutcome(
                    model_path="Assets/Source.fbx", succeeded=True, bone_names=["Hips"]
                ),
                SkeletonExportOutcome(
                    model_path="Assets/Target.fbx", succeeded=True, bone_names=["Hips"]
                ),
            ]
        )

    monkeypatch.setattr(smv, "run_export", fake_run_export)

    items = smv.check_retarget(
        "Unity.exe", tmp_path, "Assets/Source.fbx", "Assets/Target.fbx"
    )

    assert len(items) == 1
    assert items[0].severity == "info"


def test_check_retarget_model_load_failure(tmp_path, monkeypatch):
    def fake_run_export(unity_path, project_path, model_paths, timeout_s=600):
        return SkeletonExportRunResult(
            outcomes=[
                SkeletonExportOutcome(
                    model_path="Assets/Source.fbx", succeeded=False, error="bad model"
                ),
                SkeletonExportOutcome(
                    model_path="Assets/Target.fbx", succeeded=True, bone_names=["Hips"]
                ),
            ]
        )

    monkeypatch.setattr(smv, "run_export", fake_run_export)

    items = smv.check_retarget(
        "Unity.exe", tmp_path, "Assets/Source.fbx", "Assets/Target.fbx"
    )

    assert any(i.severity == "error" for i in items)


def test_check_retarget_whole_run_error(tmp_path, monkeypatch):
    def fake_run_export(unity_path, project_path, model_paths, timeout_s=600):
        return SkeletonExportRunResult(error="Unity did not finish within 10 minutes")

    monkeypatch.setattr(smv, "run_export", fake_run_export)

    items = smv.check_retarget(
        "Unity.exe", tmp_path, "Assets/Source.fbx", "Assets/Target.fbx"
    )

    assert len(items) == 1
    assert items[0].severity == "error"


# --- run_state_machine_retarget_validation (orchestration) ------------------


def test_run_combines_both_checks(tmp_path, monkeypatch):
    _write_controller(tmp_path, "Player.controller", _CONTROLLER)

    def fake_run_export(unity_path, project_path, model_paths, timeout_s=600):
        return SkeletonExportRunResult(
            outcomes=[
                SkeletonExportOutcome(
                    model_path="Assets/Source.fbx", succeeded=True, bone_names=["Hips"]
                ),
                SkeletonExportOutcome(
                    model_path="Assets/Target.fbx", succeeded=True, bone_names=["Hips"]
                ),
            ]
        )

    monkeypatch.setattr(smv, "run_export", fake_run_export)

    finding = smv.run_state_machine_retarget_validation(
        tmp_path,
        "1",
        unity_path="Unity.exe",
        source_model_path="Assets/Source.fbx",
        target_model_path="Assets/Target.fbx",
    )

    assert finding.status == STATUS_FLAGGED  # unreachable/dead-end states present
    issue_types = {i.detail.get("issue_type") for i in finding.items}
    assert "unreachable_state" in issue_types


def test_run_skips_retarget_when_not_fully_specified(tmp_path):
    _write_controller(tmp_path, "Player.controller", _CONTROLLER)

    finding = smv.run_state_machine_retarget_validation(tmp_path, "1", unity_path="Unity.exe")

    # No source/target model given -> retarget check skipped, only state-machine items present.
    issue_types = {i.detail.get("issue_type") for i in finding.items}
    assert "unmapped_bone" not in issue_types


def test_run_no_checks_requested_is_pass(tmp_path):
    finding = smv.run_state_machine_retarget_validation(tmp_path, "1", check_states=False)
    assert finding.status == STATUS_PASS
    assert finding.items == []


# --- StateMachineValidationService --------------------------------------


def _setup_service():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    service = smv.StateMachineValidationService(findings)
    project = projects.create("Moonlit Depths")
    return service, projects, project


def test_service_check_states_persists_and_history(tmp_path):
    service, projects, project = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")
    _write_controller(tmp_path, "Player.controller", _CONTROLLER)

    finding, record = service.check_states(project)

    assert record.feature_id == smv.FEATURE_ID
    assert service.history(project.id) == [record]


def test_service_check_retarget_uses_project_alias_prefixes(tmp_path, monkeypatch):
    service, projects, project = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")
    project = projects.set_retarget_alias_prefixes(project.id, "rig:")

    def fake_run_export(unity_path, project_path, model_paths, timeout_s=600):
        return SkeletonExportRunResult(
            outcomes=[
                SkeletonExportOutcome(
                    model_path="Assets/Source.fbx", succeeded=True, bone_names=["rig:Hips"]
                ),
                SkeletonExportOutcome(
                    model_path="Assets/Target.fbx", succeeded=True, bone_names=["Hips"]
                ),
            ]
        )

    monkeypatch.setattr(smv, "run_export", fake_run_export)

    finding, _record = service.check_retarget(
        project, "Unity.exe", "Assets/Source.fbx", "Assets/Target.fbx"
    )

    assert finding.status == STATUS_PASS  # "rig:Hips" matched "Hips" via the custom prefix


def test_service_check_retarget_default_alias_prefixes(tmp_path, monkeypatch):
    service, projects, project = _setup_service()
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")

    def fake_run_export(unity_path, project_path, model_paths, timeout_s=600):
        return SkeletonExportRunResult(
            outcomes=[
                SkeletonExportOutcome(
                    model_path="Assets/Source.fbx",
                    succeeded=True,
                    bone_names=["mixamorig:Hips"],
                ),
                SkeletonExportOutcome(
                    model_path="Assets/Target.fbx", succeeded=True, bone_names=["Hips"]
                ),
            ]
        )

    monkeypatch.setattr(smv, "run_export", fake_run_export)

    finding, _record = service.check_retarget(
        project, "Unity.exe", "Assets/Source.fbx", "Assets/Target.fbx"
    )

    assert finding.status == STATUS_PASS


# --- CLI ---------------------------------------------------------------


def test_cli_state_machine_check(tmp_path, capsys):
    _write_controller(tmp_path, "Player.controller", _CONTROLLER)

    exit_code = smv._cli([str(tmp_path)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "flagged" in out


def test_cli_json_flag(tmp_path, capsys):
    _write_controller(tmp_path, "Player.controller", _CONTROLLER)

    exit_code = smv._cli([str(tmp_path), "--json"])

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert exit_code == 0
    assert parsed["feature_id"] == smv.FEATURE_ID


def test_cli_skip_states_with_no_retarget_args_is_empty(tmp_path, capsys):
    exit_code = smv._cli([str(tmp_path), "--skip-states"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No state machines or skeletons checked." in out
