"""Trailer & Screenshot Checklist use-case (Phase G, section 7, Stretch tier).

Scope decision: only screenshots are analyzed. A shipped trailer is a video
with audio and motion over time; Spiced has no tooling here to decode or
reason about that ("no gameplay shown early" is a claim about content and
pacing across a timeline, not something a deterministic local check or a
text-only AI pass can verify) — deep trailer analysis is explicitly out of
scope. For screenshots, Spiced runs local, deterministic checks via Pillow
(resolution/aspect-ratio sanity against common store requirements, plus a
low-color-variance heuristic that flags likely-blank/loading-screen shots
for the developer's own review) and then asks the AI to review the *set* —
but only the filenames, the deterministic findings, and whatever caption
text the developer supplies about each shot. Raw image bytes are never sent
to the AI provider; this module never even hands them to the prompt builder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_screenshot_checklist_prompt
from spiced.storage.projects import Project
from spiced.storage.screenshot_checklist_reports import (
    ScreenshotChecklistReport,
    ScreenshotChecklistReportRepository,
)

# Steam recommends at least 1920x1080 (16:9) for screenshot assets; itch has
# no hard minimum, but very small/oddly-cropped shots still read poorly on
# any store page. These are common, documented-as-of-writing sanity checks,
# not a live fetch of each platform's current requirements — see the
# reminder baked into the AI response format.
MIN_WIDTH = 1280
MIN_HEIGHT = 720
RECOMMENDED_WIDTH = 1920
RECOMMENDED_HEIGHT = 1080
TARGET_ASPECT = 16 / 9
ASPECT_TOLERANCE = 0.15
# Below this pixel-value standard deviation (0-255 grayscale scale), a shot
# reads as "mostly empty/blank" (a loading screen, a solid-color background,
# a black frame) — worth a flag for manual review, not a hard rejection.
BLANK_VARIANCE_THRESHOLD = 8.0


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class UnreadableImageError(RuntimeError):
    """Raised when Pillow can't open a supplied file as an image."""


@dataclass(frozen=True)
class ScreenshotFinding:
    filename: str
    width: int
    height: int
    aspect_ratio: float
    meets_min_resolution: bool
    meets_recommended_resolution: bool
    aspect_ratio_ok: bool
    likely_blank: bool
    color_stddev: float
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScreenshotChecklistFindings:
    findings: list[ScreenshotFinding]

    @property
    def flagged_count(self) -> int:
        return sum(
            1
            for f in self.findings
            if f.likely_blank or not f.aspect_ratio_ok or not f.meets_min_resolution
        )


@dataclass(frozen=True)
class ScreenshotChecklistResult:
    findings: ScreenshotChecklistFindings
    response_text: str
    provider: str
    report: ScreenshotChecklistReport | None


def _color_stddev(image: Image.Image) -> float:
    """A cheap, deterministic "how much visual variance is here" proxy.

    Downsamples to keep this fast on large screenshots, converts to
    grayscale, and returns the pixel-value standard deviation. A near-solid
    image (loading screen, black frame, plain menu background) scores low;
    real gameplay/art scores meaningfully higher. This is a heuristic, not
    content understanding — it can be fooled by a busy-but-near-monochrome
    shot, which is why findings are framed as "worth a look," not a verdict.
    """
    small = image.convert("L").resize((128, 128))
    pixels = list(small.getdata())
    if not pixels:
        return 0.0
    mean = sum(pixels) / len(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    return variance**0.5


def analyze_screenshot(path: str | Path) -> ScreenshotFinding:
    path = Path(path)
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            stddev = _color_stddev(image)
    except (OSError, UnidentifiedImageError) as exc:
        raise UnreadableImageError(f'Could not read "{path.name}" as an image: {exc}') from exc

    aspect = width / height if height else 0.0
    aspect_ok = abs(aspect - TARGET_ASPECT) <= TARGET_ASPECT * ASPECT_TOLERANCE
    meets_min = width >= MIN_WIDTH and height >= MIN_HEIGHT
    meets_recommended = width >= RECOMMENDED_WIDTH and height >= RECOMMENDED_HEIGHT
    likely_blank = stddev < BLANK_VARIANCE_THRESHOLD

    notes = []
    if not meets_min:
        notes.append(f"Below the common {MIN_WIDTH}x{MIN_HEIGHT} minimum ({width}x{height}).")
    elif not meets_recommended:
        notes.append(
            f"Below the {RECOMMENDED_WIDTH}x{RECOMMENDED_HEIGHT} store-recommended size "
            f"({width}x{height}) — still usable, just softer at full size."
        )
    if not aspect_ok:
        notes.append(f"Aspect ratio {aspect:.2f}:1 is far from the common 16:9 ({width}x{height}).")
    if likely_blank:
        notes.append(
            "Low color variance — reads as a likely loading/blank/solid-color shot. Worth a "
            "manual look before including it."
        )

    return ScreenshotFinding(
        filename=path.name,
        width=width,
        height=height,
        aspect_ratio=aspect,
        meets_min_resolution=meets_min,
        meets_recommended_resolution=meets_recommended,
        aspect_ratio_ok=aspect_ok,
        likely_blank=likely_blank,
        color_stddev=round(stddev, 2),
        notes=notes,
    )


def scan_screenshots(paths: list[str]) -> ScreenshotChecklistFindings:
    """Run the deterministic Pillow-based checks on each path.

    Raises ``UnreadableImageError`` (naming the offending file) on the first
    file Pillow can't open — callers show that to the developer rather than
    silently skipping a bad upload.
    """
    return ScreenshotChecklistFindings(findings=[analyze_screenshot(p) for p in paths])


class TrailerScreenshotChecklistService:
    def __init__(self, reports: ScreenshotChecklistReportRepository) -> None:
        self._reports = reports

    def analyze(
        self,
        provider: AIProvider,
        findings: ScreenshotChecklistFindings,
        *,
        captions: dict[str, str] | None = None,
        project: Project | None = None,
        record_usage=None,
    ) -> ScreenshotChecklistResult:
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )
        prompt = build_screenshot_checklist_prompt(
            findings.findings,
            captions=captions or {},
            project_name=project.name if project else None,
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        report = None
        if project is not None:
            report = self._reports.create(
                project_id=project.id,
                findings_json=json.dumps([_finding_dict(f) for f in findings.findings]),
                ai_summary=response.text,
                provider=response.provider,
            )
        return ScreenshotChecklistResult(
            findings=findings,
            response_text=response.text,
            provider=response.provider,
            report=report,
        )

    def history(self, project_id: int, limit: int = 20) -> list[ScreenshotChecklistReport]:
        return self._reports.list_for_project(project_id, limit=limit)


def _finding_dict(finding: ScreenshotFinding) -> dict:
    return {
        "filename": finding.filename,
        "width": finding.width,
        "height": finding.height,
        "aspect_ratio": finding.aspect_ratio,
        "meets_min_resolution": finding.meets_min_resolution,
        "meets_recommended_resolution": finding.meets_recommended_resolution,
        "aspect_ratio_ok": finding.aspect_ratio_ok,
        "likely_blank": finding.likely_blank,
        "color_stddev": finding.color_stddev,
        "notes": finding.notes,
    }
