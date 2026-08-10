"""Tests for automation.mocap_cleanup_assist (Implementation Bible,
Feature 12). No mocking, no live engine -- everything here runs for real
against small, hand-generated BVH fixtures with a deliberately induced
foot-slide segment and a deliberately induced single-frame jitter spike,
matching the Bible's stated acceptance criteria."""

from __future__ import annotations

from spiced.automation import mocap_cleanup_assist as mca
from spiced.automation.finding import STATUS_ERROR, STATUS_FLAGGED, STATUS_PASS
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

FRAME_TIME = 1.0 / 30.0
N_FRAMES = 20
# Grounded phases: frames 0-4 and 10-14; swing (airborne) otherwise.
_GROUNDED = set(range(0, 5)) | set(range(10, 15))


def _bvh_text(hips_x, leftfoot_x, leftfoot_y, spine_rot_z) -> str:
    lines = [
        "HIERARCHY",
        "ROOT Hips",
        "{",
        "    OFFSET 0.0 0.0 0.0",
        "    CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation",
        "    JOINT LeftFoot",
        "    {",
        "        OFFSET 0.0 -1.0 0.0",
        "        CHANNELS 3 Xposition Yposition Zposition",
        "    }",
        "    JOINT Spine",
        "    {",
        "        OFFSET 0.0 0.3 0.0",
        "        CHANNELS 1 Zrotation",
        "    }",
        "}",
        "MOTION",
        f"Frames: {N_FRAMES}",
        f"Frame Time: {FRAME_TIME}",
    ]
    for i in range(N_FRAMES):
        lines.append(
            f"{hips_x[i]} 1.0 0.0 0.0 0.0 0.0 "
            f"{leftfoot_x[i]} {leftfoot_y[i]} 0.0 {spine_rot_z[i]}"
        )
    return "\n".join(lines) + "\n"


def _clean_bvh() -> str:
    hips_x = [i * 0.05 for i in range(N_FRAMES)]
    # Foot stays exactly under the hips in X at all times -- world X is
    # constant (0.0) whenever grounded, so it's never sliding.
    leftfoot_x = [-hips_x[i] for i in range(N_FRAMES)]
    leftfoot_y = [0.0 if i in _GROUNDED else 0.3 for i in range(N_FRAMES)]
    spine_rot_z = [i * 2.0 for i in range(N_FRAMES)]  # smooth trend, no spike
    return _bvh_text(hips_x, leftfoot_x, leftfoot_y, spine_rot_z)


def _dirty_bvh() -> str:
    """Same base motion as the clean fixture, with two deliberately
    induced defects: the foot doesn't compensate for hips motion during
    the first grounded phase (frames 0-4) -- a real drag/slide -- and the
    Spine's rotation spikes for exactly one frame (12) then returns."""
    hips_x = [i * 0.05 for i in range(N_FRAMES)]
    leftfoot_x = []
    for i in range(N_FRAMES):
        if i < 5:
            leftfoot_x.append(0.0)  # NOT compensating -- foot drags with the body
        else:
            leftfoot_x.append(-hips_x[i])
    leftfoot_y = [0.0 if i in _GROUNDED else 0.3 for i in range(N_FRAMES)]
    spine_rot_z = [i * 2.0 for i in range(N_FRAMES)]
    spine_rot_z[12] = spine_rot_z[12] + 80.0  # single-frame jitter spike
    return _bvh_text(hips_x, leftfoot_x, leftfoot_y, spine_rot_z)


# --- guess_foot_joint_names --------------------------------------------------


def test_guess_foot_joint_names_matches_by_name():
    from spiced.automation.bvh_mocap import parse_bvh

    skeleton = parse_bvh(_clean_bvh())
    assert mca.guess_foot_joint_names(skeleton) == ["LeftFoot"]


# --- analyze_bvh_mocap / run_mocap_cleanup_assist ----------------------------


def test_clean_bvh_produces_no_flags(tmp_path):
    path = tmp_path / "clean.bvh"
    path.write_text(_clean_bvh(), encoding="utf-8")

    finding = mca.run_mocap_cleanup_assist(path, "1")

    assert finding.status == STATUS_PASS
    assert finding.items == []


def test_dirty_bvh_catches_foot_sliding_and_jitter(tmp_path):
    path = tmp_path / "dirty.bvh"
    path.write_text(_dirty_bvh(), encoding="utf-8")

    finding = mca.run_mocap_cleanup_assist(path, "1")

    assert finding.status == STATUS_FLAGGED
    issue_types = {i.detail["issue_type"] for i in finding.items}
    assert issue_types == {"foot_sliding", "jitter_frame"}

    slide_items = [i for i in finding.items if i.detail["issue_type"] == "foot_sliding"]
    assert slide_items[0].detail["joint"] == "LeftFoot"

    jitter_items = [i for i in finding.items if i.detail["issue_type"] == "jitter_frame"]
    assert jitter_items[0].detail["joint"] == "Spine"
    assert jitter_items[0].detail["frame"] == 12


def test_run_mocap_cleanup_assist_unreadable_file_is_error(tmp_path):
    path = tmp_path / "broken.bvh"
    path.write_text("not a bvh file", encoding="utf-8")

    finding = mca.run_mocap_cleanup_assist(path, "1")

    assert finding.status == STATUS_ERROR
    assert finding.items[0].severity == "error"


def test_run_mocap_cleanup_assist_missing_file_is_error(tmp_path):
    finding = mca.run_mocap_cleanup_assist(tmp_path / "missing.bvh", "1")
    assert finding.status == STATUS_ERROR


def test_explicit_foot_joint_names_override_guess(tmp_path):
    path = tmp_path / "dirty.bvh"
    path.write_text(_dirty_bvh(), encoding="utf-8")

    finding = mca.run_mocap_cleanup_assist(path, "1", foot_joint_names=[])
    # No foot joints checked -> only jitter should be found.
    issue_types = {i.detail["issue_type"] for i in finding.items}
    assert "foot_sliding" not in issue_types
    assert "jitter_frame" in issue_types


# --- MocapCleanupAssistService ------------------------------------------


def test_service_scan_persists_finding(tmp_path):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    service = mca.MocapCleanupAssistService(findings)

    path = tmp_path / "clean.bvh"
    path.write_text(_clean_bvh(), encoding="utf-8")

    finding, record = service.scan(project, path)

    assert record.feature_id == mca.FEATURE_ID
    assert findings.list_for_project(project.id) == [record]


def test_service_history_filters_by_feature_id():
    from spiced.automation.finding import Finding

    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    service = mca.MocapCleanupAssistService(findings)
    findings.create(
        project.id,
        Finding(feature_id=mca.FEATURE_ID, project_id=str(project.id), status=STATUS_PASS,
                summary="a"),
    )
    findings.create(
        project.id,
        Finding(feature_id="vfx.other", project_id=str(project.id), status=STATUS_PASS,
                summary="b"),
    )

    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].feature_id == mca.FEATURE_ID


# --- CLI --------------------------------------------------------------------


def test_cli_prints_summary_and_returns_zero_on_clean(tmp_path, capsys):
    path = tmp_path / "clean.bvh"
    path.write_text(_clean_bvh(), encoding="utf-8")

    exit_code = mca._cli([str(path)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Clean take" in out


def test_cli_json_flag_prints_finding_dict(tmp_path, capsys):
    import json

    path = tmp_path / "dirty.bvh"
    path.write_text(_dirty_bvh(), encoding="utf-8")

    exit_code = mca._cli([str(path), "--json"])
    out = capsys.readouterr().out

    assert exit_code == 0
    parsed = json.loads(out)
    assert parsed["feature_id"] == mca.FEATURE_ID
