"""Mix/Level QA (Phase I, section 8, Phase 2 tier).

**No ``audioop``**: the stdlib ``audioop`` module was removed in Python 3.13
(``import audioop`` raises ``ModuleNotFoundError`` on the Python this project
runs on) -- this module uses only the stdlib ``wave`` module to open WAV
files and the stdlib ``array`` module to unpack raw PCM frames by hand, then
computes peak amplitude, RMS, and silence-gap detection itself. No third-
party audio library is used or needed.

**WAV only, by design** -- not an oversight. Decoding ``.mp3``/``.ogg``
would require a new third-party dependency (there is no stdlib decoder for
either), which this phase deliberately avoids. WAV is the most portable
format to analyze with only the standard library, so compressed formats are
simply not analyzed by this feature; every result and the Audio screen's
copy say so explicitly.

**Sample format scope**: only 8-bit unsigned and 16-bit signed integer PCM
WAV (by far the most common formats for game audio assets) are analyzed.
24-bit and 32-bit float WAV raise ``UnsupportedWavError`` with a clear
message rather than being silently mis-decoded.

**Multi-channel scope**: only the first channel is analyzed for
stereo/multi-channel files -- a documented simplification rather than
mixing channels down, which would need its own (unverifiable) assumptions
about how to combine channels.

Batch loudness-outlier detection is a simple, honestly-scoped statistical
comparison (z-score against the batch's own mean/stdev of RMS level) -- it
flags a file whose *average level* is a clear outlier relative to the rest
of the batch it was run against, not any absolute "correct" loudness
target, and needs at least 3 files to say anything meaningful.
"""

from __future__ import annotations

import array
import struct
import sys
import wave
from dataclasses import dataclass, field
from math import sqrt
from pathlib import Path
from statistics import mean, pstdev

from spiced.storage.mix_qa_reports import MixQaReport, MixQaReportRepository
from spiced.storage.projects import Project

WAV_ONLY_CAVEAT = (
    "WAV files only -- compressed formats (.mp3, .ogg) are not analyzed by this feature. "
    "Decoding those would need a new third-party dependency Spiced deliberately doesn't add; "
    "WAV is the most portable format to analyze with just the standard library. Only 8-bit and "
    "16-bit integer PCM WAV are read (24-bit/32-bit float are reported as unsupported rather "
    "than silently mis-decoded), and only the first channel of multi-channel audio is analyzed."
)

# Below this fraction of full scale, a sample counts as "near-zero" for
# silence-gap detection.
SILENCE_THRESHOLD_RATIO = 0.02
MIN_SILENCE_SECONDS = 2.0
# At/above this fraction of full scale, a sample counts toward clipping risk.
CLIPPING_RATIO_THRESHOLD = 0.98
# ...and clipping risk is only flagged once at least this fraction of all
# samples hit that peak (a single stray full-scale sample isn't clipping).
CLIPPING_MIN_SAMPLE_FRACTION = 0.001
# A batch needs at least this many files before "relative outlier" means
# anything statistically.
MIN_BATCH_SIZE_FOR_OUTLIERS = 3
OUTLIER_ZSCORE_THRESHOLD = 2.0


class UnsupportedWavError(RuntimeError):
    """Raised for a WAV file Spiced can't analyze (bad header, or not 8/16-bit PCM)."""


@dataclass(frozen=True)
class SilenceGap:
    start_seconds: float
    duration_seconds: float


@dataclass(frozen=True)
class WavAnalysis:
    path: str
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width_bytes: int
    peak_ratio: float  # 0..1 of full scale
    rms_ratio: float  # 0..1 of full scale
    clipping_risk: bool
    silence_gaps: list[SilenceGap] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "duration_seconds": round(self.duration_seconds, 2),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "sample_width_bytes": self.sample_width_bytes,
            "peak_ratio": round(self.peak_ratio, 4),
            "rms_ratio": round(self.rms_ratio, 4),
            "clipping_risk": self.clipping_risk,
            "silence_gaps": [
                {
                    "start_seconds": round(g.start_seconds, 2),
                    "duration_seconds": round(g.duration_seconds, 2),
                }
                for g in self.silence_gaps
            ],
        }


def _read_pcm_channel0(path: str | Path) -> tuple[list[int], int, int, int, int]:
    """Returns ``(samples, sample_rate, channels, sample_width_bytes,
    max_value)`` for channel 0 only. Samples are re-centered on zero (8-bit
    WAV PCM is stored unsigned, centered at 128)."""
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            rate = wf.getframerate()
            nframes = wf.getnframes()
            raw = wf.readframes(nframes)
    except (wave.Error, EOFError, struct.error) as exc:
        raise UnsupportedWavError(f"{Path(path).name}: not a readable WAV file ({exc})") from exc

    if channels < 1:
        raise UnsupportedWavError(f"{Path(path).name}: WAV header reports 0 channels.")

    if sampwidth == 1:
        arr = array.array("B", raw)
        channel0 = arr[0::channels]
        samples = [v - 128 for v in channel0]
        max_val = 127
    elif sampwidth == 2:
        # WAV PCM is always little-endian; array.array uses native byte
        # order, so byteswap on a big-endian host to decode correctly.
        arr = array.array("h", raw[: len(raw) - (len(raw) % 2)])
        if sys.byteorder == "big":
            arr.byteswap()
        samples = list(arr[0::channels])
        max_val = 32767
    else:
        raise UnsupportedWavError(
            f"{Path(path).name}: unsupported sample width ({sampwidth * 8}-bit) -- only 8-bit "
            "and 16-bit integer PCM WAV are analyzed by Mix/Level QA."
        )

    return samples, rate, channels, sampwidth, max_val


def _find_silence_gaps(samples: list[int], rate: int, max_val: int) -> list[SilenceGap]:
    if not samples or rate <= 0:
        return []
    threshold = max_val * SILENCE_THRESHOLD_RATIO
    min_run = int(MIN_SILENCE_SECONDS * rate)
    gaps: list[SilenceGap] = []
    run_start: int | None = None
    for i, s in enumerate(samples):
        if abs(s) <= threshold:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and i - run_start >= min_run:
                gaps.append(SilenceGap(run_start / rate, (i - run_start) / rate))
            run_start = None
    if run_start is not None and len(samples) - run_start >= min_run:
        gaps.append(SilenceGap(run_start / rate, (len(samples) - run_start) / rate))
    return gaps


def analyze_wav(path: str | Path) -> WavAnalysis:
    """Analyze one WAV file's peak amplitude, RMS level, clipping risk, and
    silence gaps. Raises ``UnsupportedWavError`` (naming the file) if it
    can't be read or isn't 8/16-bit integer PCM."""
    path = Path(path)
    samples, rate, channels, sampwidth, max_val = _read_pcm_channel0(path)

    n = len(samples)
    duration = n / rate if rate else 0.0
    peak = max((abs(s) for s in samples), default=0)
    peak_ratio = peak / max_val if max_val else 0.0
    rms = sqrt(sum(s * s for s in samples) / n) if n else 0.0
    rms_ratio = rms / max_val if max_val else 0.0

    clip_threshold = max_val * CLIPPING_RATIO_THRESHOLD
    clip_count = sum(1 for s in samples if abs(s) >= clip_threshold)
    clipping_risk = n > 0 and (clip_count / n) >= CLIPPING_MIN_SAMPLE_FRACTION

    gaps = _find_silence_gaps(samples, rate, max_val)

    return WavAnalysis(
        path=str(path),
        duration_seconds=duration,
        sample_rate=rate,
        channels=channels,
        sample_width_bytes=sampwidth,
        peak_ratio=peak_ratio,
        rms_ratio=rms_ratio,
        clipping_risk=clipping_risk,
        silence_gaps=gaps,
    )


def _find_loudness_outliers(files: list[WavAnalysis]) -> list[str]:
    if len(files) < MIN_BATCH_SIZE_FOR_OUTLIERS:
        return []
    rms_values = [f.rms_ratio for f in files]
    avg = mean(rms_values)
    spread = pstdev(rms_values)
    if spread == 0:
        return []
    return [f.path for f in files if abs(f.rms_ratio - avg) / spread > OUTLIER_ZSCORE_THRESHOLD]


@dataclass(frozen=True)
class MixQaBatchResult:
    files: list[WavAnalysis] = field(default_factory=list)
    unreadable: list[tuple[str, str]] = field(default_factory=list)
    loudness_outliers: list[str] = field(default_factory=list)
    caveat: str = WAV_ONLY_CAVEAT

    def as_summary_dict(self) -> dict:
        return {
            "files": [f.as_dict() for f in self.files],
            "unreadable": [{"path": p, "error": e} for p, e in self.unreadable],
            "loudness_outliers": self.loudness_outliers,
        }


def analyze_wav_batch(paths: list[str]) -> MixQaBatchResult:
    files: list[WavAnalysis] = []
    unreadable: list[tuple[str, str]] = []
    for p in paths:
        try:
            files.append(analyze_wav(p))
        except UnsupportedWavError as exc:
            unreadable.append((str(p), str(exc)))
    outliers = _find_loudness_outliers(files)
    return MixQaBatchResult(files=files, unreadable=unreadable, loudness_outliers=outliers)


def find_wav_files(folder_path: str | Path) -> list[str]:
    root = Path(folder_path)
    if not root.is_dir():
        return []
    return sorted(str(p) for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".wav")


class MixLevelQaService:
    def __init__(self, reports: MixQaReportRepository) -> None:
        self._reports = reports

    def scan_folder(
        self, folder_path: str, *, project: Project | None = None
    ) -> tuple[MixQaBatchResult, MixQaReport | None]:
        result = analyze_wav_batch(find_wav_files(folder_path))
        report = None
        if project is not None:
            report = self._reports.create(project.id, result.as_summary_dict())
        return result, report

    def history(self, project_id: int, limit: int = 20) -> list[MixQaReport]:
        return self._reports.list_for_project(project_id, limit=limit)
