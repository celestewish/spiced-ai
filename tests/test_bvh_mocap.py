"""Tests for automation.bvh_mocap (Implementation Bible, Feature 12's BVH
parser + forward kinematics). Runs for real against small, hand-written
BVH text fixtures -- no mocking, this is pure parsing/math."""

from __future__ import annotations

import pytest

from spiced.automation import bvh_mocap as bvh

_SIMPLE_BVH = """HIERARCHY
ROOT Hips
{
    OFFSET 0.0 0.0 0.0
    CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
    JOINT LeftFoot
    {
        OFFSET 0.0 -1.0 0.0
        CHANNELS 3 Zrotation Xrotation Yrotation
        End Site
        {
            OFFSET 0.0 -0.5 0.0
        }
    }
}
MOTION
Frames: 3
Frame Time: 0.033333
0.0 1.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
0.5 1.0 0.0 0.0 0.0 0.0 10.0 0.0 0.0
1.0 1.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
"""


def test_parse_bvh_reads_hierarchy_and_motion():
    skeleton = bvh.parse_bvh(_SIMPLE_BVH)
    assert skeleton.joint_names == ["Hips", "LeftFoot"]
    assert skeleton.frame_time == pytest.approx(0.033333)
    assert len(skeleton.frames) == 3
    assert skeleton.joints[0].channels == [
        "Xposition", "Yposition", "Zposition", "Zrotation", "Xrotation", "Yrotation",
    ]
    assert skeleton.joints[1].offset == (0.0, -1.0, 0.0)


def test_parse_bvh_rejects_garbage():
    with pytest.raises(bvh.BvhParseError):
        bvh.parse_bvh("not a bvh file at all")


def test_parse_bvh_rejects_truncated_motion_data():
    truncated = _SIMPLE_BVH.rsplit("\n", 2)[0]  # drop the last motion frame line
    with pytest.raises(bvh.BvhParseError):
        bvh.parse_bvh(truncated)


def test_compute_world_positions_root_translation():
    skeleton = bvh.parse_bvh(_SIMPLE_BVH)
    positions = bvh.compute_world_positions(skeleton)
    hips = positions["Hips"]
    assert [s.position for s in hips] == [(0.0, 1.0, 0.0), (0.5, 1.0, 0.0), (1.0, 1.0, 0.0)]


def test_compute_world_positions_child_offset_from_parent():
    skeleton = bvh.parse_bvh(_SIMPLE_BVH)
    positions = bvh.compute_world_positions(skeleton)
    # LeftFoot has offset (0, -1, 0) from Hips and no position channels of
    # its own -- at frame 0 (no rotation anywhere), its world position is
    # exactly Hips' position plus that offset.
    foot0 = positions["LeftFoot"][0].position
    assert foot0 == pytest.approx((0.0, 0.0, 0.0))


def test_local_rotation_samples_reads_rotation_channels_in_xyz_order():
    skeleton = bvh.parse_bvh(_SIMPLE_BVH)
    rotations = bvh.local_rotation_samples(skeleton)
    foot_rot = rotations["LeftFoot"]
    # Frame 1's channel values (in file order Zrotation, Xrotation,
    # Yrotation) are 10.0, 0.0, 0.0 -- i.e. Zrotation=10 -- and
    # local_rotation_samples always emits (X, Y, Z) regardless of the
    # file's channel order, so that's (0.0, 0.0, 10.0) here.
    assert foot_rot[1].rotation_deg == pytest.approx((0.0, 0.0, 10.0))


def test_local_rotation_samples_skips_joints_with_no_rotation_channels():
    text = _SIMPLE_BVH.replace(
        "CHANNELS 3 Zrotation Xrotation Yrotation", "CHANNELS 3 Xposition Yposition Zposition"
    )
    skeleton = bvh.parse_bvh(text)
    rotations = bvh.local_rotation_samples(skeleton)
    assert "LeftFoot" not in rotations
    assert "Hips" in rotations  # Hips still has rotation channels
