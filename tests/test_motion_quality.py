"""Tests for automation.motion_quality (Implementation Bible, Features 11 &
12's shared foot-sliding/snap/jitter detection helper). Pure math, no
mocking needed -- every test builds synthetic sample sequences directly."""

from __future__ import annotations

from spiced.automation import motion_quality as mq


def _pos_samples(positions, fps=30.0):
    return [mq.PositionSample(i, i / fps, p) for i, p in enumerate(positions)]


def _rot_samples(rotations, fps=30.0):
    return [mq.RotationSample(i, i / fps, r) for i, r in enumerate(rotations)]


# --- detect_foot_sliding -----------------------------------------------------


def test_detect_foot_sliding_flags_grounded_moving_foot():
    # Foot stays low (grounded) but keeps moving in X for several frames --
    # a real drag/slide.
    positions = [(float(i) * 0.2, 0.0, 0.0) for i in range(10)]
    samples = _pos_samples(positions)

    events = mq.detect_foot_sliding(
        "LeftFoot", samples, contact_height=0.05, slide_speed_threshold=0.1
    )

    assert len(events) == 1
    assert events[0].joint == "LeftFoot"
    # Frame 0 has no prior sample to measure a speed from -- the run starts
    # at frame 1, the first frame with a measurable, over-threshold speed.
    assert events[0].start_frame == 1
    assert events[0].peak_speed > 0.1


def test_detect_foot_sliding_no_flag_when_planted_still():
    # Grounded and stationary -- the foot correctly stays put.
    positions = [(0.0, 0.0, 0.0) for _ in range(10)]
    samples = _pos_samples(positions)

    events = mq.detect_foot_sliding(
        "LeftFoot", samples, contact_height=0.05, slide_speed_threshold=0.1
    )
    assert events == []


def test_detect_foot_sliding_no_flag_when_airborne_and_moving():
    # Moving fast, but well above the ground (mid-swing) -- not sliding.
    positions = [(float(i) * 0.5, 0.5, 0.0) for i in range(10)]
    samples = _pos_samples(positions)

    events = mq.detect_foot_sliding(
        "LeftFoot", samples, contact_height=0.05, slide_speed_threshold=0.1
    )
    assert events == []


def test_detect_foot_sliding_ignores_brief_single_frame_blips():
    # A one-frame out-and-back excursion produces a 2-frame elevated-speed
    # run (the trip out, then the trip back) -- with min_event_frames=3,
    # that short a run should still be filtered out as capture noise.
    positions = [(0.0, 0.0, 0.0)] * 3 + [(0.2, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * 3
    samples = _pos_samples(positions)

    events = mq.detect_foot_sliding(
        "LeftFoot", samples, contact_height=0.05, slide_speed_threshold=0.1,
        min_event_frames=3,
    )
    assert events == []


def test_detect_foot_sliding_requires_at_least_two_samples():
    assert mq.detect_foot_sliding("F", [], contact_height=0.05, slide_speed_threshold=0.1) == []
    assert (
        mq.detect_foot_sliding(
            "F", _pos_samples([(0, 0, 0)]), contact_height=0.05, slide_speed_threshold=0.1
        )
        == []
    )


# --- detect_angular_velocity_spikes (snap detection) -------------------------


def test_detect_angular_velocity_spikes_flags_instant_large_rotation():
    rotations = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (170.0, 0.0, 0.0), (170.0, 0.0, 0.0)]
    samples = _rot_samples(rotations)

    events = mq.detect_angular_velocity_spikes("Spine", samples, threshold_deg_s=500.0)

    assert len(events) == 1
    assert events[0].frame == 2
    assert events[0].angular_speed_deg_s > 500.0


def test_detect_angular_velocity_spikes_no_flag_for_smooth_blend():
    # 90 degrees spread evenly over 30 frames (1 second) is a normal blend.
    rotations = [(i * 3.0, 0.0, 0.0) for i in range(31)]
    samples = _rot_samples(rotations)

    events = mq.detect_angular_velocity_spikes("Spine", samples, threshold_deg_s=500.0)
    assert events == []


# --- detect_single_frame_jitter ----------------------------------------------


def test_detect_single_frame_jitter_flags_spike_and_return():
    # Smooth trend, one frame spikes far off and the next frame returns to
    # the trend -- textbook raw-mocap jitter.
    rotations = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (60.0, 0.0, 0.0), (20.0, 0.0, 0.0),
                 (30.0, 0.0, 0.0)]
    samples = _rot_samples(rotations)

    events = mq.detect_single_frame_jitter("Elbow", samples, jitter_threshold_deg=15.0)

    assert len(events) == 1
    assert events[0].frame == 2


def test_detect_single_frame_jitter_no_flag_for_sustained_change():
    # A real, sustained direction change -- not an isolated spike.
    rotations = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (60.0, 0.0, 0.0), (110.0, 0.0, 0.0),
                 (160.0, 0.0, 0.0)]
    samples = _rot_samples(rotations)

    events = mq.detect_single_frame_jitter("Elbow", samples, jitter_threshold_deg=15.0)
    assert events == []


def test_detect_single_frame_jitter_needs_neighbors_on_both_sides():
    rotations = [(0.0, 0.0, 0.0), (60.0, 0.0, 0.0)]
    samples = _rot_samples(rotations)
    assert mq.detect_single_frame_jitter("Elbow", samples, jitter_threshold_deg=5.0) == []


def test_detect_single_frame_jitter_clean_sequence_flags_nothing():
    rotations = [(i * 2.0, 0.0, 0.0) for i in range(20)]
    samples = _rot_samples(rotations)
    assert mq.detect_single_frame_jitter("Elbow", samples, jitter_threshold_deg=5.0) == []
