"""Shared motion-quality detection helpers (Implementation Bible, Features
11 & 12).

Foot-sliding detection, "snap" detection, and single-frame jitter detection
all reduce to the same underlying question over a joint's position/rotation
time series: did this joint move (or rotate) in a way that's implausible
given its neighbors in time. Feature 11 (live Unity Play Mode capture) and
Feature 12 (offline BVH mocap scan) both need foot-sliding detection over a
joint position time series -- per the Bible's own instruction ("factor that
math into a shared helper both features import, rather than duplicating
it"), that math lives here, once, and both features import it rather than
each re-deriving its own version.

Every function here operates on plain per-joint sample lists -- neither
knows or cares whether the data came from a live Unity capture (Feature 11)
or a parsed BVH file (Feature 12), which is what lets both features share
this module without either depending on the other's I/O layer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class PositionSample:
    frame: int
    time_s: float
    position: Vec3


@dataclass(frozen=True)
class RotationSample:
    frame: int
    time_s: float
    # Euler angles in degrees (x, y, z). Fine for "how far did this rotate
    # between two adjacent frames over a short timestep" -- gimbal lock only
    # matters for large excursions, not frame-to-frame deltas, and every
    # caller here only ever compares neighboring frames.
    rotation_deg: Vec3


@dataclass(frozen=True)
class FootSlideEvent:
    joint: str
    start_frame: int
    end_frame: int
    start_time_s: float
    end_time_s: float
    peak_speed: float  # units/sec, horizontal (XZ) plane


@dataclass(frozen=True)
class SnapEvent:
    joint: str
    frame: int
    time_s: float
    angular_speed_deg_s: float


@dataclass(frozen=True)
class JitterEvent:
    joint: str
    frame: int
    time_s: float
    deviation_deg: float


def _horizontal_distance(a: Vec3, b: Vec3) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


def _angular_delta_deg(a: Vec3, b: Vec3) -> float:
    """Euclidean distance between two euler-angle triples, in degrees. A
    coarse but adequate proxy for "how far apart are these two rotations"
    over the small frame-to-frame deltas every caller here uses it for."""
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def detect_foot_sliding(
    joint: str,
    samples: list[PositionSample],
    *,
    contact_height: float,
    slide_speed_threshold: float,
    min_event_frames: int = 2,
) -> list[FootSlideEvent]:
    """Flags contiguous frame ranges where ``joint`` is near the ground
    (``position.y <= contact_height`` -- "grounded") but still moving in
    the horizontal (XZ) plane faster than ``slide_speed_threshold``.

    A planted foot should stay put in world space regardless of how fast
    the character's root is moving (that's what root motion means -- the
    body travels, the planted foot doesn't); one that keeps moving while
    grounded is being dragged along with the body instead of staying
    planted, which is foot sliding. ``samples`` must be time-ordered
    samples of a single joint (use one call per foot joint).
    """
    if len(samples) < 2:
        return []

    speeds = [0.0]
    for prev, cur in zip(samples, samples[1:], strict=False):
        dt = cur.time_s - prev.time_s
        speed = _horizontal_distance(prev.position, cur.position) / dt if dt > 0 else 0.0
        speeds.append(speed)

    events: list[FootSlideEvent] = []
    run_start: int | None = None
    run_peak = 0.0
    for i, sample in enumerate(samples):
        grounded = sample.position[1] <= contact_height
        sliding = grounded and speeds[i] > slide_speed_threshold
        if sliding:
            if run_start is None:
                run_start = i
                run_peak = speeds[i]
            else:
                run_peak = max(run_peak, speeds[i])
            continue
        if run_start is not None and (i - run_start) >= min_event_frames:
            events.append(
                FootSlideEvent(
                    joint=joint,
                    start_frame=samples[run_start].frame,
                    end_frame=samples[i - 1].frame,
                    start_time_s=samples[run_start].time_s,
                    end_time_s=samples[i - 1].time_s,
                    peak_speed=run_peak,
                )
            )
        run_start = None
        run_peak = 0.0

    if run_start is not None and (len(samples) - run_start) >= min_event_frames:
        events.append(
            FootSlideEvent(
                joint=joint,
                start_frame=samples[run_start].frame,
                end_frame=samples[-1].frame,
                start_time_s=samples[run_start].time_s,
                end_time_s=samples[-1].time_s,
                peak_speed=run_peak,
            )
        )
    return events


def detect_angular_velocity_spikes(
    joint: str,
    samples: list[RotationSample],
    *,
    threshold_deg_s: float,
) -> list[SnapEvent]:
    """Flags a frame-to-frame rotation change whose implied angular
    velocity exceeds ``threshold_deg_s`` -- a real, measurable "snap"
    (near-instantaneous large rotation), as opposed to a blend, which
    spreads the same total rotation change across many frames and so never
    produces one single huge per-frame delta."""
    events: list[SnapEvent] = []
    for prev, cur in zip(samples, samples[1:], strict=False):
        dt = cur.time_s - prev.time_s
        if dt <= 0:
            continue
        speed = _angular_delta_deg(prev.rotation_deg, cur.rotation_deg) / dt
        if speed > threshold_deg_s:
            events.append(SnapEvent(joint=joint, frame=cur.frame, time_s=cur.time_s,
                                     angular_speed_deg_s=speed))
    return events


def detect_single_frame_jitter(
    joint: str,
    samples: list[RotationSample],
    *,
    jitter_threshold_deg: float,
) -> list[JitterEvent]:
    """Flags a single frame whose rotation spikes away from its neighbors'
    interpolated trend and then immediately returns -- the classic raw-
    mocap noise artifact. Requires a neighbor on both sides, so the first
    and last frame in ``samples`` are never flagged (there's nothing to
    compare them against)."""
    events: list[JitterEvent] = []
    for i in range(1, len(samples) - 1):
        prev, cur, nxt = samples[i - 1], samples[i], samples[i + 1]
        span = nxt.time_s - prev.time_s
        if span <= 0:
            continue
        t = (cur.time_s - prev.time_s) / span
        expected = tuple(
            prev.rotation_deg[k] + (nxt.rotation_deg[k] - prev.rotation_deg[k]) * t
            for k in range(3)
        )
        deviation = _angular_delta_deg(cur.rotation_deg, expected)
        # Requiring the deviation to exceed how far apart the neighbors
        # themselves are is what isolates "spike and immediately return"
        # from a real, sustained rotation change -- a sustained change
        # moves prev/next apart too, a single-frame jitter spike doesn't.
        neighbor_gap = _angular_delta_deg(prev.rotation_deg, nxt.rotation_deg)
        if deviation > jitter_threshold_deg and deviation > neighbor_gap:
            events.append(
                JitterEvent(joint=joint, frame=cur.frame, time_s=cur.time_s,
                            deviation_deg=deviation)
            )
    return events
