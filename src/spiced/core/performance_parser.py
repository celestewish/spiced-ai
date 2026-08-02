"""Deterministic performance/profiling data parser.

Spiced never runs a profiler itself — the developer pastes or imports numbers
they already gathered (frame time/fps, memory, and load time, per location or
asset), and this module turns that into structured samples and flagged spikes
locally. The AI step only interprets this structured, trustworthy output; it
never re-parses the raw text.

Accepted formats:
    JSON: a list of ``{"location": ..., "fps": ..., "memory_mb": ..., "load_time_s": ...}``
        objects, or an object with a ``"samples"`` list in that shape.
    CSV: a header row naming any of ``location``/``fps``/``memory_mb``/``load_time_s``.
    Text: one location per line, e.g. ``"Waterfall Area: fps=42, memory=850MB, load=3.2s"``.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

FORMAT_TEXT = "text"
FORMAT_CSV = "csv"
FORMAT_JSON = "json"

MAX_EXCERPT_CHARS = 2000
MAX_SAMPLES = 200

# Spike thresholds. Frame-rate targets are a common indie baseline (30fps
# "playable", 60fps smooth); memory/load thresholds are conservative defaults
# a solo dev can reasonably expect to review, not hard engine limits.
FPS_SEVERE = 30
FPS_NOTABLE = 45
MEMORY_JUMP_RATIO = 1.5
MEMORY_JUMP_MIN_MB = 50
LOAD_TIME_NOTABLE_S = 5.0
LOAD_TIME_SEVERE_S = 10.0

SEVERITY_NOTABLE = "notable"
SEVERITY_SEVERE = "severe"

_TEXT_LOCATION_RE = re.compile(r"^\s*(?P<location>.+?)\s*(?:[:\-–—]+)\s*(?P<rest>.+)$")
# Both "42fps" and "fps=42"/"fps: 42" styles are common in pasted notes.
_FPS_RE = re.compile(
    r"(?:(?P<v1>\d+(?:\.\d+)?)\s*fps\b)|(?:\bfps\D{0,4}(?P<v2>\d+(?:\.\d+)?))", re.IGNORECASE
)
_MEMORY_RE = re.compile(
    r"(?:(?:memory|mem)\D{0,4}(?P<v1>\d+(?:\.\d+)?)\s*mb\b)|(?:(?P<v2>\d+(?:\.\d+)?)\s*mb\b)",
    re.IGNORECASE,
)
_LOAD_RE = re.compile(
    r"load(?:\s*time)?\D{0,4}(?P<value>\d+(?:\.\d+)?)\s*s\b", re.IGNORECASE
)


@dataclass
class PerformanceSample:
    location: str
    fps: float | None = None
    memory_mb: float | None = None
    load_time_s: float | None = None


@dataclass
class PerformanceSpike:
    location: str
    metric: str  # "fps" | "memory_mb" | "load_time_s"
    value: float
    severity: str  # SEVERITY_NOTABLE | SEVERITY_SEVERE

    @property
    def message(self) -> str:
        if self.metric == "fps":
            return f"Frame rate drops to {self.value:g}fps near {self.location}."
        if self.metric == "memory_mb":
            return f"Memory jumps to {self.value:g}MB near {self.location}."
        return f"Load time reaches {self.value:g}s near {self.location}."


@dataclass
class ParsedPerformance:
    source_format: str
    samples: list[PerformanceSample] = field(default_factory=list)
    spikes: list[PerformanceSpike] = field(default_factory=list)
    excerpt: str = ""
    confidence: str = CONFIDENCE_LOW

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def avg_fps(self) -> float | None:
        return _avg([s.fps for s in self.samples if s.fps is not None])

    @property
    def min_fps(self) -> float | None:
        values = [s.fps for s in self.samples if s.fps is not None]
        return min(values) if values else None

    @property
    def peak_memory_mb(self) -> float | None:
        values = [s.memory_mb for s in self.samples if s.memory_mb is not None]
        return max(values) if values else None

    @property
    def max_load_time_s(self) -> float | None:
        values = [s.load_time_s for s in self.samples if s.load_time_s is not None]
        return max(values) if values else None

    def as_summary_dict(self) -> dict:
        return {
            "source_format": self.source_format,
            "sample_count": self.sample_count,
            "avg_fps": self.avg_fps,
            "min_fps": self.min_fps,
            "peak_memory_mb": self.peak_memory_mb,
            "max_load_time_s": self.max_load_time_s,
            "spikes": [
                {
                    "location": s.location,
                    "metric": s.metric,
                    "value": s.value,
                    "severity": s.severity,
                }
                for s in self.spikes
            ],
            "confidence": self.confidence,
        }


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def parse_performance_data(text: str) -> ParsedPerformance:
    stripped = text.strip()
    if not stripped:
        return ParsedPerformance(FORMAT_TEXT, confidence=CONFIDENCE_LOW)

    if stripped[0] in "{[":
        parsed = _try_parse_json(stripped)
        if parsed is not None:
            return _finish(parsed)
    if _looks_like_csv(stripped):
        parsed = _try_parse_csv(stripped)
        if parsed is not None:
            return _finish(parsed)
    return _finish(_parse_text(text))


def _finish(parsed: ParsedPerformance) -> ParsedPerformance:
    parsed.spikes = _detect_spikes(parsed.samples)
    return parsed


def _detect_spikes(samples: list[PerformanceSample]) -> list[PerformanceSpike]:
    spikes: list[PerformanceSpike] = []
    avg_memory = _avg([s.memory_mb for s in samples if s.memory_mb is not None])
    for sample in samples:
        if sample.fps is not None:
            if sample.fps < FPS_SEVERE:
                spikes.append(PerformanceSpike(sample.location, "fps", sample.fps, SEVERITY_SEVERE))
            elif sample.fps < FPS_NOTABLE:
                spikes.append(
                    PerformanceSpike(sample.location, "fps", sample.fps, SEVERITY_NOTABLE)
                )
        if sample.memory_mb is not None and avg_memory:
            jump = sample.memory_mb - avg_memory
            if sample.memory_mb >= avg_memory * MEMORY_JUMP_RATIO and jump >= MEMORY_JUMP_MIN_MB:
                spikes.append(
                    PerformanceSpike(
                        sample.location, "memory_mb", sample.memory_mb, SEVERITY_NOTABLE
                    )
                )
        if sample.load_time_s is not None:
            if sample.load_time_s >= LOAD_TIME_SEVERE_S:
                spikes.append(
                    PerformanceSpike(
                        sample.location, "load_time_s", sample.load_time_s, SEVERITY_SEVERE
                    )
                )
            elif sample.load_time_s >= LOAD_TIME_NOTABLE_S:
                spikes.append(
                    PerformanceSpike(
                        sample.location, "load_time_s", sample.load_time_s, SEVERITY_NOTABLE
                    )
                )
    return spikes


def _cap(text: str) -> str:
    if len(text) > MAX_EXCERPT_CHARS:
        return text[:MAX_EXCERPT_CHARS].rstrip() + "\n… (truncated)"
    return text


def _looks_like_csv(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    first = next(csv.reader(io.StringIO(lines[0])), [])
    header_lower = [c.strip().lower() for c in first]
    known_headers = ("location", "fps", "memory_mb", "load_time_s", "memory", "load_time")
    return any(h in known_headers for h in header_lower)


def _try_parse_csv(text: str) -> ParsedPerformance | None:
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return None
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        return None

    header = [c.strip().lower() for c in rows[0]]
    aliases = {
        "location": "location",
        "fps": "fps",
        "memory_mb": "memory_mb",
        "memory": "memory_mb",
        "load_time_s": "load_time_s",
        "load_time": "load_time_s",
    }
    columns = {aliases[h]: i for i, h in enumerate(header) if h in aliases}
    if "location" not in columns:
        return None

    samples: list[PerformanceSample] = []
    for row in rows[1:]:
        cells = [c.strip() for c in row]
        location = _cell(cells, columns.get("location"))
        if not location:
            continue
        samples.append(
            PerformanceSample(
                location=location,
                fps=_float_cell(cells, columns.get("fps")),
                memory_mb=_float_cell(cells, columns.get("memory_mb")),
                load_time_s=_float_cell(cells, columns.get("load_time_s")),
            )
        )
        if len(samples) >= MAX_SAMPLES:
            break

    if not samples:
        return None
    confidence = CONFIDENCE_HIGH if len(columns) >= 2 else CONFIDENCE_MEDIUM
    return ParsedPerformance(FORMAT_CSV, samples, [], _cap(text.strip()), confidence)


def _cell(cells: list[str], idx: int | None) -> str | None:
    if idx is None or idx >= len(cells):
        return None
    return cells[idx] or None


def _float_cell(cells: list[str], idx: int | None) -> float | None:
    raw = _cell(cells, idx)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _try_parse_json(text: str) -> ParsedPerformance | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("samples"), list):
        items = data["samples"]
    if items is None:
        return None

    samples: list[PerformanceSample] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        location = str(item.get("location") or item.get("name") or item.get("scene") or "").strip()
        if not location:
            continue
        samples.append(
            PerformanceSample(
                location=location,
                fps=_num(item, "fps"),
                memory_mb=_num(item, "memory_mb", "memory"),
                load_time_s=_num(item, "load_time_s", "load_time"),
            )
        )
        if len(samples) >= MAX_SAMPLES:
            break

    if not samples:
        return None
    excerpt = _cap(json.dumps(data)[:MAX_EXCERPT_CHARS])
    return ParsedPerformance(FORMAT_JSON, samples, [], excerpt, CONFIDENCE_HIGH)


def _num(item: dict, *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _parse_text(text: str) -> ParsedPerformance:
    samples: list[PerformanceSample] = []
    relevant: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _TEXT_LOCATION_RE.match(line)
        location = match.group("location").strip() if match else line
        rest = match.group("rest") if match else line
        fps = _search_float(_FPS_RE, rest)
        memory = _search_float(_MEMORY_RE, rest)
        load_time = _search_float(_LOAD_RE, rest)
        if fps is None and memory is None and load_time is None:
            continue
        samples.append(
            PerformanceSample(location=location, fps=fps, memory_mb=memory, load_time_s=load_time)
        )
        relevant.append(line)
        if len(samples) >= MAX_SAMPLES:
            break

    confidence = CONFIDENCE_MEDIUM if samples else CONFIDENCE_LOW
    excerpt = _cap("\n".join(relevant)) if relevant else _cap(text.strip())
    return ParsedPerformance(FORMAT_TEXT, samples, [], excerpt, confidence)


def _search_float(pattern: re.Pattern, text: str) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    for group in match.groups():
        if group is not None:
            try:
                return float(group)
            except ValueError:
                return None
    return None
