"""Minimal BVH (Biovision Hierarchy) mocap file parser + forward kinematics
(Implementation Bible, Feature 12).

BVH is a plain-text, well-documented format -- a ``HIERARCHY`` block
(nested ``ROOT``/``JOINT``/``End Site`` definitions, each with an
``OFFSET`` and a ``CHANNELS`` list) followed by a ``MOTION`` block (a frame
count, a frame time, then one line of channel values per frame). This
module only implements what Feature 12 (Mocap Cleanup Assist) needs from
that: per-joint per-frame **world position** (via straightforward forward
kinematics over rotation/translation channels) for foot-sliding detection,
and per-joint per-frame **local rotation values** (read directly off the
rotation channels, no FK needed) for jitter detection.

Not a general-purpose BVH toolkit -- no export, no channel reordering
beyond what's needed to build a rotation matrix, and End Site offsets
(leaf markers with no channels of their own) are parsed and skipped rather
than exposed, since neither foot-sliding nor jitter detection needs them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from spiced.automation.motion_quality import PositionSample, RotationSample

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class BvhJoint:
    name: str
    parent: str | None
    offset: Vec3
    channels: list[str]  # e.g. ["Xposition", ..., "Zrotation", "Xrotation", "Yrotation"]


@dataclass(frozen=True)
class BvhSkeleton:
    joints: list[BvhJoint] = field(default_factory=list)
    frame_time: float = 1.0 / 30.0
    frames: list[list[float]] = field(default_factory=list)  # raw channel values per frame

    @property
    def joint_names(self) -> list[str]:
        return [j.name for j in self.joints]


class BvhParseError(ValueError):
    """Raised for a file that doesn't look like well-formed BVH."""


def parse_bvh(text: str) -> BvhSkeleton:
    tokens = text.replace("{", " { ").replace("}", " } ").split()
    pos = [0]

    def peek() -> str | None:
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def advance() -> str:
        if pos[0] >= len(tokens):
            raise BvhParseError("Unexpected end of file while parsing BVH.")
        tok = tokens[pos[0]]
        pos[0] += 1
        return tok

    def expect(value: str) -> str:
        tok = advance()
        if tok != value:
            raise BvhParseError(f"Expected {value!r}, got {tok!r}.")
        return tok

    joints: list[BvhJoint] = []

    def parse_joint_body(name: str, parent: str | None) -> None:
        expect("{")
        offset: Vec3 = (0.0, 0.0, 0.0)
        while True:
            tok = peek()
            if tok is None:
                raise BvhParseError(f"Unterminated joint block for {name!r}.")
            if tok == "OFFSET":
                advance()
                offset = (float(advance()), float(advance()), float(advance()))
            elif tok == "CHANNELS":
                advance()
                n = int(advance())
                channels = [advance() for _ in range(n)]
                joints.append(BvhJoint(name=name, parent=parent, offset=offset, channels=channels))
            elif tok == "JOINT":
                advance()
                child_name = advance()
                parse_joint_body(child_name, name)
            elif tok == "End":
                advance()
                advance()  # "Site"
                expect("{")
                while peek() != "}":
                    advance()
                expect("}")
            elif tok == "}":
                advance()
                return
            else:
                raise BvhParseError(f"Unexpected token {tok!r} inside joint {name!r}.")

    expect("HIERARCHY")
    expect("ROOT")
    root_name = advance()
    parse_joint_body(root_name, None)

    expect("MOTION")
    expect("Frames:")
    num_frames = int(advance())
    expect("Frame")
    expect("Time:")
    frame_time = float(advance())

    total_channels = sum(len(j.channels) for j in joints)
    remaining = tokens[pos[0]:]
    if len(remaining) < num_frames * total_channels:
        raise BvhParseError(
            f"Expected {num_frames * total_channels} motion values, found {len(remaining)}."
        )
    frames = [
        [float(v) for v in remaining[i * total_channels:(i + 1) * total_channels]]
        for i in range(num_frames)
    ]

    return BvhSkeleton(joints=joints, frame_time=frame_time, frames=frames)


def _axis_rotation_matrix(axis: str, degrees: float) -> np.ndarray:
    rad = np.radians(degrees)
    c, s = np.cos(rad), np.sin(rad)
    if axis == "X":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "Y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    if axis == "Z":
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    raise ValueError(f"Unknown rotation axis: {axis!r}")


def _local_matrix(joint: BvhJoint, values: list[float]) -> np.ndarray:
    translation = np.array(joint.offset, dtype=float)
    rotation = np.eye(3)
    for channel, value in zip(joint.channels, values, strict=True):
        axis = channel[0].upper()
        if channel.endswith("position"):
            idx = {"X": 0, "Y": 1, "Z": 2}[axis]
            translation[idx] += value
        elif channel.endswith("rotation"):
            rotation = rotation @ _axis_rotation_matrix(axis, value)
    m = np.eye(4)
    m[:3, :3] = rotation
    m[:3, 3] = translation
    return m


def compute_world_positions(skeleton: BvhSkeleton) -> dict[str, list[PositionSample]]:
    """Per-joint, time-ordered world-space position samples across every
    frame, via forward kinematics. Joints are processed in file order,
    which for a well-formed BVH hierarchy always places a parent before
    its children."""
    channel_offsets: dict[str, int] = {}
    idx = 0
    for j in skeleton.joints:
        channel_offsets[j.name] = idx
        idx += len(j.channels)

    result: dict[str, list[PositionSample]] = {j.name: [] for j in skeleton.joints}
    for frame_idx, frame_values in enumerate(skeleton.frames):
        time_s = frame_idx * skeleton.frame_time
        world_mats: dict[str, np.ndarray] = {}
        for j in skeleton.joints:
            start = channel_offsets[j.name]
            values = frame_values[start:start + len(j.channels)]
            local = _local_matrix(j, values)
            world = local if j.parent is None else world_mats[j.parent] @ local
            world_mats[j.name] = world
            pos = (float(world[0, 3]), float(world[1, 3]), float(world[2, 3]))
            result[j.name].append(PositionSample(frame_idx, time_s, pos))
    return result


def local_rotation_samples(skeleton: BvhSkeleton) -> dict[str, list[RotationSample]]:
    """Per-joint, time-ordered local rotation samples, read directly off
    each joint's own rotation channels (no FK -- jitter detection compares
    a joint's own rotation curve to itself, not its world-space pose)."""
    channel_offsets: dict[str, int] = {}
    idx = 0
    for j in skeleton.joints:
        channel_offsets[j.name] = idx
        idx += len(j.channels)

    result: dict[str, list[RotationSample]] = {}
    for j in skeleton.joints:
        rot_channels = [c for c in j.channels if c.endswith("rotation")]
        if not rot_channels:
            continue
        start = channel_offsets[j.name]
        local_idx = {c: i for i, c in enumerate(j.channels)}
        samples: list[RotationSample] = []
        for frame_idx, frame_values in enumerate(skeleton.frames):
            values = frame_values[start:start + len(j.channels)]
            # Always emitted in a fixed (X, Y, Z) axis order regardless of
            # the file's own channel order -- consistent enough for the
            # magnitude-based deltas detect_single_frame_jitter computes,
            # without needing to track per-file channel order downstream.
            by_axis = {"X": 0.0, "Y": 0.0, "Z": 0.0}
            for channel in rot_channels:
                axis = channel[0].upper()
                by_axis[axis] = values[local_idx[channel]]
            samples.append(
                RotationSample(frame_idx, frame_idx * skeleton.frame_time,
                                (by_axis["X"], by_axis["Y"], by_axis["Z"]))
            )
        result[j.name] = samples
    return result
