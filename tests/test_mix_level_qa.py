"""Tests for core.mix_level_qa: clipping/silence/outlier detection on
synthetic WAV data generated in-memory via the stdlib `wave` module (no
audioop, no real audio fixtures needed -- see the module's own docstring
for why audioop specifically is never imported)."""

from __future__ import annotations

import math
import wave

import pytest

from spiced.core.mix_level_qa import (
    MIN_SILENCE_SECONDS,
    UnsupportedWavError,
    analyze_wav,
    analyze_wav_batch,
    find_wav_files,
)

SAMPLE_RATE = 8000


def _write_wav(path, samples: list[int], *, rate: int = SAMPLE_RATE, sampwidth: int = 2):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        if sampwidth == 2:
            import array

            arr = array.array("h", samples)
            wf.writeframes(arr.tobytes())
        else:
            import array

            arr = array.array("B", [s + 128 for s in samples])
            wf.writeframes(arr.tobytes())


def _sine(duration_seconds: float, amplitude: int, rate: int = SAMPLE_RATE) -> list[int]:
    n = int(duration_seconds * rate)
    return [int(amplitude * math.sin(2 * math.pi * 220 * i / rate)) for i in range(n)]


def test_clear_clipping_case_flagged(tmp_path):
    # A big block of samples pinned at full scale.
    samples = [32767] * (SAMPLE_RATE // 2) + [-32768] * (SAMPLE_RATE // 2)
    path = tmp_path / "clipped.wav"
    _write_wav(path, samples)

    analysis = analyze_wav(path)
    assert analysis.clipping_risk is True
    assert analysis.peak_ratio > 0.99


def test_normal_case_not_flagged_as_clipping(tmp_path):
    samples = _sine(1.0, amplitude=10000)
    path = tmp_path / "normal.wav"
    _write_wav(path, samples)

    analysis = analyze_wav(path)
    assert analysis.clipping_risk is False
    assert 0 < analysis.peak_ratio < 0.5


def test_clear_silence_gap_detected(tmp_path):
    tone = _sine(1.0, amplitude=15000)
    silence = [0] * int((MIN_SILENCE_SECONDS + 1) * SAMPLE_RATE)
    samples = tone + silence + tone
    path = tmp_path / "with_silence.wav"
    _write_wav(path, samples)

    analysis = analyze_wav(path)
    assert len(analysis.silence_gaps) == 1
    gap = analysis.silence_gaps[0]
    assert gap.duration_seconds >= MIN_SILENCE_SECONDS
    # The gap should start right after the first second of tone.
    assert 0.9 <= gap.start_seconds <= 1.1


def test_short_quiet_run_not_flagged_as_silence_gap(tmp_path):
    tone = _sine(1.0, amplitude=15000)
    brief_quiet = [0] * int(0.2 * SAMPLE_RATE)  # well under MIN_SILENCE_SECONDS
    samples = tone + brief_quiet + tone
    path = tmp_path / "brief_quiet.wav"
    _write_wav(path, samples)

    analysis = analyze_wav(path)
    assert analysis.silence_gaps == []


def test_duration_and_metadata_reported(tmp_path):
    samples = _sine(2.0, amplitude=5000)
    path = tmp_path / "two_seconds.wav"
    _write_wav(path, samples)

    analysis = analyze_wav(path)
    assert analysis.sample_rate == SAMPLE_RATE
    assert analysis.channels == 1
    assert analysis.sample_width_bytes == 2
    assert 1.9 <= analysis.duration_seconds <= 2.1


def test_unsupported_sample_width_raises(tmp_path):
    path = tmp_path / "bad.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(3)  # 24-bit -- unsupported by this scoped-down feature
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"\0" * 300)
    with pytest.raises(UnsupportedWavError):
        analyze_wav(path)


def test_not_a_wav_file_raises(tmp_path):
    path = tmp_path / "not_audio.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a wav file")
    with pytest.raises(UnsupportedWavError):
        analyze_wav(path)


def test_batch_flags_relative_loudness_outlier(tmp_path):
    # Slightly varied amplitudes (not identical) so the "normal" group has
    # some natural spread -- 4 perfectly identical values plus 1 outlier
    # would make the outlier's z-score land exactly at the threshold by
    # construction, which isn't representative of real mixed audio.
    quiet_amplitudes = [2800, 3000, 3200, 2900, 3100]
    quiet_paths = []
    for i, amp in enumerate(quiet_amplitudes):
        p = tmp_path / f"quiet_{i}.wav"
        _write_wav(p, _sine(1.0, amplitude=amp))
        quiet_paths.append(str(p))
    loud_path = tmp_path / "loud.wav"
    _write_wav(loud_path, _sine(1.0, amplitude=30000))

    result = analyze_wav_batch(quiet_paths + [str(loud_path)])
    assert str(loud_path) in result.loudness_outliers


def test_batch_too_small_reports_no_outliers(tmp_path):
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    _write_wav(a, _sine(1.0, amplitude=3000))
    _write_wav(b, _sine(1.0, amplitude=30000))
    result = analyze_wav_batch([str(a), str(b)])
    assert result.loudness_outliers == []


def test_batch_reports_unreadable_files_without_raising(tmp_path):
    good = tmp_path / "good.wav"
    _write_wav(good, _sine(1.0, amplitude=3000))
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"garbage")
    result = analyze_wav_batch([str(good), str(bad)])
    assert len(result.files) == 1
    assert len(result.unreadable) == 1


def test_find_wav_files_only_matches_wav_extension(tmp_path):
    (tmp_path / "sub").mkdir()
    _write_wav(tmp_path / "sub" / "a.wav", _sine(0.1, amplitude=1000))
    (tmp_path / "b.mp3").write_bytes(b"\0")
    found = find_wav_files(tmp_path)
    assert len(found) == 1
    assert found[0].endswith("a.wav")
