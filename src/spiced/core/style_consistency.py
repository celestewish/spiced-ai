"""Style Consistency Checker (Phase I, section 8, Phase 2 tier).

Compares an asset against the *statistics* of the project's existing asset
population -- average resolution, aspect-ratio distribution, and a cheap
dominant-color proxy (Pillow's palette quantization) -- and flags a clear
outlier. This is inherently a **relative/statistical heuristic, not true
"style" understanding**: Spiced has no model of art style, line weight,
shading technique, or intent. Two assets can share identical palette/
resolution statistics and look nothing alike; two assets can look
consistent to a human eye and still differ enough numerically to be flagged.
Every result says so, in the module and in the UI, the same honesty
discipline as Localization Readiness's documented heuristic shape.

Reuses ``core.asset_review_queue.review_asset``'s per-image resolution
reading rather than re-implementing it, but needs its own dominant-color
extraction (the review queue doesn't compute one), so this module still
opens each image itself with Pillow -- there was no scan result to
meaningfully "reuse" beyond resolution, which is a one-line call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

from PIL import Image, UnidentifiedImageError

STYLE_CONSISTENCY_CAVEAT = (
    "A statistical outlier check against this project's own existing assets -- resolution, "
    "aspect ratio, and a cheap reduced-palette dominant color -- NOT true style understanding. "
    "Spiced has no model of art style, linework, or shading technique. An asset can be flagged "
    "here and still be stylistically perfect (e.g. a deliberately larger hero asset), and an "
    "asset that looks inconsistent to a human eye can still pass these numeric checks. Treat "
    "every flag as 'worth a second look,' never a verdict."
)

# Outlier thresholds: relative difference from the population average beyond
# which a value counts as a "clear" outlier, not just ordinary variation.
RESOLUTION_TOLERANCE = 0.5  # +/-50% of the population's average width/height
ASPECT_RATIO_TOLERANCE = 0.35
COLOR_DISTANCE_THRESHOLD = 90.0  # Euclidean distance in 0-255 RGB space
MIN_POPULATION_SIZE = 2


class UnreadableImageError(RuntimeError):
    """Raised when Pillow can't open a supplied file as an image."""


@dataclass(frozen=True)
class AssetStats:
    path: str
    width: int
    height: int
    aspect_ratio: float
    dominant_color: tuple[int, int, int] | None


def _extract_stats(path: str | Path) -> AssetStats | None:
    """Returns ``None`` (rather than raising) for files that can't be
    opened as an image -- population-scan callers skip unreadable files
    silently; the single "new asset" entry point raises instead, since that
    one really is the developer's direct input."""
    try:
        with Image.open(path) as img:
            img.load()
            width, height = img.size
            small = img.convert("RGB").resize((32, 32))
            quantized = small.quantize(colors=5)
            counts = quantized.getcolors() or []
            palette = quantized.getpalette() or []
    except (OSError, UnidentifiedImageError):
        return None
    dominant = None
    if counts and palette:
        _, dominant_index = max(counts, key=lambda c: c[0])
        offset = dominant_index * 3
        if offset + 3 <= len(palette):
            dominant = (palette[offset], palette[offset + 1], palette[offset + 2])
    aspect = width / height if height else 0.0
    return AssetStats(
        path=str(path), width=width, height=height, aspect_ratio=aspect, dominant_color=dominant
    )


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def _average_color(colors: list[tuple[int, int, int]]) -> tuple[int, int, int] | None:
    if not colors:
        return None
    return (
        round(mean(c[0] for c in colors)),
        round(mean(c[1] for c in colors)),
        round(mean(c[2] for c in colors)),
    )


@dataclass(frozen=True)
class StyleOutlierFinding:
    path: str
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StyleConsistencyResult:
    population_size: int
    outliers: list[StyleOutlierFinding] = field(default_factory=list)
    caveat: str = STYLE_CONSISTENCY_CAVEAT


def _compare_to_baseline(
    candidate: AssetStats,
    avg_width: float,
    avg_height: float,
    avg_aspect: float,
    avg_color: tuple[int, int, int] | None,
) -> list[str]:
    reasons: list[str] = []
    if avg_width and abs(candidate.width - avg_width) / avg_width > RESOLUTION_TOLERANCE:
        reasons.append(
            f"Width {candidate.width}px is far from the population average ({avg_width:.0f}px)."
        )
    if avg_height and abs(candidate.height - avg_height) / avg_height > RESOLUTION_TOLERANCE:
        reasons.append(
            f"Height {candidate.height}px is far from the population average ({avg_height:.0f}px)."
        )
    if avg_aspect and abs(candidate.aspect_ratio - avg_aspect) > ASPECT_RATIO_TOLERANCE:
        reasons.append(
            f"Aspect ratio {candidate.aspect_ratio:.2f}:1 is far from the population average "
            f"({avg_aspect:.2f}:1)."
        )
    if avg_color and candidate.dominant_color:
        distance = _color_distance(avg_color, candidate.dominant_color)
        if distance > COLOR_DISTANCE_THRESHOLD:
            reasons.append(
                f"Dominant color {candidate.dominant_color} is a clear outlier vs. the "
                f"population's average palette {avg_color} (color distance {distance:.0f})."
            )
    return reasons


def check_style_consistency(
    new_asset_path: str | Path, population_paths: list[str]
) -> StyleConsistencyResult:
    """Compare one new asset's stats against the population's average."""
    candidate = _extract_stats(new_asset_path)
    if candidate is None:
        raise UnreadableImageError(f'Could not read "{new_asset_path}" as an image.')

    population = [s for s in (_extract_stats(p) for p in population_paths) if s is not None]
    if len(population) < MIN_POPULATION_SIZE:
        return StyleConsistencyResult(population_size=len(population), outliers=[])

    avg_width = mean(s.width for s in population)
    avg_height = mean(s.height for s in population)
    avg_aspect = mean(s.aspect_ratio for s in population)
    avg_color = _average_color([s.dominant_color for s in population if s.dominant_color])

    reasons = _compare_to_baseline(candidate, avg_width, avg_height, avg_aspect, avg_color)
    outliers = [StyleOutlierFinding(candidate.path, reasons)] if reasons else []
    return StyleConsistencyResult(population_size=len(population), outliers=outliers)


def scan_population_for_outliers(paths: list[str]) -> StyleConsistencyResult:
    """Leave-one-out scan: treats every asset in turn as the "new" one
    against the rest of the population, so a whole folder can be checked in
    one pass rather than requiring the developer to pick a single asset."""
    all_stats = [s for s in (_extract_stats(p) for p in paths) if s is not None]
    if len(all_stats) < MIN_POPULATION_SIZE + 1:
        return StyleConsistencyResult(population_size=len(all_stats), outliers=[])

    outliers: list[StyleOutlierFinding] = []
    for i, candidate in enumerate(all_stats):
        rest = all_stats[:i] + all_stats[i + 1 :]
        avg_width = mean(s.width for s in rest)
        avg_height = mean(s.height for s in rest)
        avg_aspect = mean(s.aspect_ratio for s in rest)
        avg_color = _average_color([s.dominant_color for s in rest if s.dominant_color])
        reasons = _compare_to_baseline(candidate, avg_width, avg_height, avg_aspect, avg_color)
        if reasons:
            outliers.append(StyleOutlierFinding(candidate.path, reasons))

    return StyleConsistencyResult(population_size=len(all_stats), outliers=outliers)
