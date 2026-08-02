"""Deterministic accessibility checklist parser.

Spiced can't see your running build, so the developer pastes or imports a
small JSON description of what to check: HUD element colors, audio-caption
coverage, and two yes/no flags. Everything here is exact, testable math —
WCAG contrast ratios and a standard simplified colorblind-simulation matrix —
not a guess. The AI step only phrases the results; it never re-derives them.

Expected JSON shape (all keys optional):
    {
      "hud_elements": [{"name": "HealthBar", "foreground": "#FF4040", "background": "#550000"}],
      "audio_files": [{"name": "cutscene_01.wav", "captioned": true}],
      "controls_remappable": true,
      "text_scaling_supported": false
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

FORMAT_JSON = "json"
FORMAT_TEXT = "text"

# WCAG 2.1 SC 1.4.11 (non-text contrast / UI components and graphics).
MIN_UI_CONTRAST = 3.0

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")

# Simplified colorblind-simulation matrices (protanopia/deuteranopia), applied
# directly to normalized 0-1 RGB. Widely used as a fast approximation; not a
# substitute for testing with real colorblind players.
_PROTANOPIA = (
    (0.567, 0.433, 0.0),
    (0.558, 0.442, 0.0),
    (0.0, 0.242, 0.758),
)
_DEUTERANOPIA = (
    (0.625, 0.375, 0.0),
    (0.7, 0.3, 0.0),
    (0.0, 0.3, 0.7),
)


def _hex_to_rgb(value: str) -> tuple[float, float, float] | None:
    match = _HEX_RE.match((value or "").strip())
    if not match:
        return None
    hex6 = match.group(1)
    return tuple(int(hex6[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb_a: tuple[float, float, float], rgb_b: tuple[float, float, float]) -> float:
    """WCAG contrast ratio between two sRGB colors, in [1, 21]."""
    l_a = _relative_luminance(rgb_a)
    l_b = _relative_luminance(rgb_b)
    lighter, darker = max(l_a, l_b), min(l_a, l_b)
    return (lighter + 0.05) / (darker + 0.05)


def _apply_matrix(rgb: tuple[float, float, float], matrix: tuple) -> tuple[float, float, float]:
    return tuple(
        min(1.0, max(0.0, sum(row[i] * rgb[i] for i in range(3)))) for row in matrix
    )  # type: ignore[return-value]


@dataclass
class ContrastCheck:
    name: str
    foreground: str
    background: str
    ratio: float
    passes: bool
    colorblind_ratio: float | None
    colorblind_safe: bool | None


@dataclass
class AccessibilityFinding:
    check: str
    message: str
    severity: str  # "fail" | "warn"


@dataclass
class ParsedAccessibility:
    source_format: str
    contrast_checks: list[ContrastCheck] = field(default_factory=list)
    caption_total: int = 0
    caption_covered: int = 0
    controls_remappable: bool | None = None
    text_scaling_supported: bool | None = None
    findings: list[AccessibilityFinding] = field(default_factory=list)
    excerpt: str = ""
    confidence: str = CONFIDENCE_LOW

    @property
    def caption_coverage_pct(self) -> float | None:
        if self.caption_total == 0:
            return None
        return round(100 * self.caption_covered / self.caption_total, 1)

    @property
    def score(self) -> int | None:
        """A simple 0-100 average across whichever checks had data."""
        parts: list[float] = []
        if self.contrast_checks:
            passing = sum(1 for c in self.contrast_checks if c.passes)
            parts.append(100 * passing / len(self.contrast_checks))
        colorblind_checks = [c for c in self.contrast_checks if c.colorblind_safe is not None]
        if colorblind_checks:
            cb_safe_count = sum(1 for c in colorblind_checks if c.colorblind_safe)
            parts.append(100 * cb_safe_count / len(colorblind_checks))
        if self.caption_coverage_pct is not None:
            parts.append(self.caption_coverage_pct)
        if self.controls_remappable is not None:
            parts.append(100.0 if self.controls_remappable else 0.0)
        if self.text_scaling_supported is not None:
            parts.append(100.0 if self.text_scaling_supported else 0.0)
        return round(sum(parts) / len(parts)) if parts else None

    def as_summary_dict(self) -> dict:
        return {
            "source_format": self.source_format,
            "score": self.score,
            "contrast_checks": [
                {
                    "name": c.name,
                    "ratio": round(c.ratio, 2),
                    "passes": c.passes,
                    "colorblind_ratio": (
                        round(c.colorblind_ratio, 2) if c.colorblind_ratio else None
                    ),
                    "colorblind_safe": c.colorblind_safe,
                }
                for c in self.contrast_checks
            ],
            "caption_coverage_pct": self.caption_coverage_pct,
            "controls_remappable": self.controls_remappable,
            "text_scaling_supported": self.text_scaling_supported,
            "findings": [
                {"check": f.check, "message": f.message, "severity": f.severity}
                for f in self.findings
            ],
            "confidence": self.confidence,
        }


def parse_accessibility_data(text: str) -> ParsedAccessibility:
    stripped = text.strip()
    if not stripped:
        return ParsedAccessibility(FORMAT_JSON, confidence=CONFIDENCE_LOW)
    if stripped[0] in "{[":
        parsed = _try_parse_json(stripped)
        if parsed is not None:
            return parsed
    # Not structured data: keep the excerpt for the AI, but no local checklist.
    excerpt = stripped[:2000]
    return ParsedAccessibility(FORMAT_TEXT, excerpt=excerpt, confidence=CONFIDENCE_LOW)


def _try_parse_json(text: str) -> ParsedAccessibility | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    contrast_checks: list[ContrastCheck] = []
    findings: list[AccessibilityFinding] = []
    for element in data.get("hud_elements") or []:
        if not isinstance(element, dict):
            continue
        name = str(element.get("name") or "HUD element")
        fg = _hex_to_rgb(str(element.get("foreground", "")))
        bg = _hex_to_rgb(str(element.get("background", "")))
        if fg is None or bg is None:
            continue
        ratio = contrast_ratio(fg, bg)
        passes = ratio >= MIN_UI_CONTRAST
        if not passes:
            findings.append(
                AccessibilityFinding(
                    "contrast",
                    f"{name}: contrast ratio {ratio:.2f}:1 is below the "
                    f"{MIN_UI_CONTRAST:g}:1 minimum.",
                    "fail",
                )
            )
        cb_ratio = None
        cb_safe = None
        worst_ratio = None
        for matrix in (_PROTANOPIA, _DEUTERANOPIA):
            sim_fg = _apply_matrix(fg, matrix)
            sim_bg = _apply_matrix(bg, matrix)
            sim_ratio = contrast_ratio(sim_fg, sim_bg)
            if worst_ratio is None or sim_ratio < worst_ratio:
                worst_ratio = sim_ratio
        if worst_ratio is not None:
            cb_ratio = worst_ratio
            cb_safe = worst_ratio >= MIN_UI_CONTRAST
            if not cb_safe:
                findings.append(
                    AccessibilityFinding(
                        "colorblind",
                        f"{name}: contrast drops to {worst_ratio:.2f}:1 under a simulated "
                        "red-green color-vision deficiency.",
                        "warn",
                    )
                )
        contrast_checks.append(
            ContrastCheck(
                name,
                str(element.get("foreground")),
                str(element.get("background")),
                ratio,
                passes,
                cb_ratio,
                cb_safe,
            )
        )

    audio_files = data.get("audio_files") or []
    caption_total = 0
    caption_covered = 0
    for audio in audio_files:
        if not isinstance(audio, dict):
            continue
        caption_total += 1
        if audio.get("captioned"):
            caption_covered += 1
    if caption_total and caption_covered < caption_total:
        findings.append(
            AccessibilityFinding(
                "captions",
                f"{caption_total - caption_covered} of {caption_total} audio files "
                "have no captions.",
                "warn",
            )
        )

    remappable = data.get("controls_remappable")
    remappable = bool(remappable) if isinstance(remappable, bool) else None
    if remappable is False:
        findings.append(
            AccessibilityFinding("controls", "Control bindings are not remappable.", "warn")
        )

    scaling = data.get("text_scaling_supported")
    scaling = bool(scaling) if isinstance(scaling, bool) else None
    if scaling is False:
        findings.append(
            AccessibilityFinding("text_scaling", "Text scaling is not supported.", "warn")
        )

    has_checklist_data = (
        contrast_checks or audio_files or remappable is not None or scaling is not None
    )
    confidence = CONFIDENCE_HIGH if has_checklist_data else CONFIDENCE_LOW
    excerpt = json.dumps(data)[:2000]
    return ParsedAccessibility(
        FORMAT_JSON,
        contrast_checks=contrast_checks,
        caption_total=caption_total,
        caption_covered=caption_covered,
        controls_remappable=remappable,
        text_scaling_supported=scaling,
        findings=findings,
        excerpt=excerpt,
        confidence=confidence,
    )
