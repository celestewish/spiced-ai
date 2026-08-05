"""Tests for core.trailer_screenshot_checklist: deterministic Pillow checks
plus the AI review-of-the-set orchestration.

Test images are generated in-memory with Pillow (no real screenshot
fixtures needed) and written to ``tmp_path``.
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import build_screenshot_checklist_prompt
from spiced.core.trailer_screenshot_checklist import (
    ProviderNotReadyError,
    ScreenshotFinding,
    TrailerScreenshotChecklistService,
    UnreadableImageError,
    analyze_screenshot,
    scan_screenshots,
)
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.screenshot_checklist_reports import ScreenshotChecklistReportRepository

CANNED = "Here's the screenshot set review."


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


def _save_solid(tmp_path, name, color, size=(1920, 1080)):
    path = tmp_path / name
    Image.new("RGB", size, color=color).save(path)
    return str(path)


def _save_busy(tmp_path, name, size=(1920, 1080)):
    """A synthetic "gameplay-like" image: a grid of large, differently
    colored blocks. High-frequency per-pixel noise averages back toward
    gray once downsampled for the variance check (the same way a real
    photo's fine detail would), so this uses large color blocks instead —
    the kind of large-scale contrast a real screenshot has plenty of.
    """
    path = tmp_path / name
    img = Image.new("RGB", size, (30, 30, 60))
    draw = ImageDraw.Draw(img)
    colors = [(220, 80, 60), (60, 180, 90), (230, 200, 40), (40, 120, 220), (200, 60, 200)]
    block = 160
    for i, x in enumerate(range(0, size[0], block)):
        for j, y in enumerate(range(0, size[1], block)):
            draw.rectangle([x, y, x + block, y + block], fill=colors[(i + j) % len(colors)])
    img.save(path)
    return str(path)


def test_analyze_screenshot_flags_blank_solid_image(tmp_path):
    path = _save_solid(tmp_path, "loading.png", (10, 10, 10))
    finding = analyze_screenshot(path)
    assert finding.likely_blank is True
    assert finding.meets_recommended_resolution is True
    assert finding.aspect_ratio_ok is True


def test_analyze_screenshot_does_not_flag_busy_image(tmp_path):
    path = _save_busy(tmp_path, "gameplay.png")
    finding = analyze_screenshot(path)
    assert finding.likely_blank is False


def test_analyze_screenshot_flags_low_resolution(tmp_path):
    path = _save_busy(tmp_path, "small.png", size=(400, 225))
    finding = analyze_screenshot(path)
    assert finding.meets_min_resolution is False
    assert finding.meets_recommended_resolution is False
    assert any("minimum" in note for note in finding.notes)


def test_analyze_screenshot_flags_unusual_aspect_ratio(tmp_path):
    path = _save_busy(tmp_path, "square.png", size=(1500, 1500))
    finding = analyze_screenshot(path)
    assert finding.aspect_ratio_ok is False


def test_analyze_screenshot_raises_on_unreadable_file(tmp_path):
    path = tmp_path / "not_an_image.png"
    path.write_text("this is not an image")
    with pytest.raises(UnreadableImageError):
        analyze_screenshot(str(path))


def test_scan_screenshots_returns_findings_for_each_path(tmp_path):
    paths = [
        _save_busy(tmp_path, "one.png"),
        _save_solid(tmp_path, "two.png", (0, 0, 0)),
    ]
    findings = scan_screenshots(paths)
    assert len(findings.findings) == 2
    assert findings.flagged_count == 1  # only the solid/blank one


def test_build_screenshot_checklist_prompt_never_includes_image_bytes():
    finding = ScreenshotFinding(
        filename="shot1.png",
        width=1920,
        height=1080,
        aspect_ratio=1.78,
        meets_min_resolution=True,
        meets_recommended_resolution=True,
        aspect_ratio_ok=True,
        likely_blank=False,
        color_stddev=42.5,
        notes=[],
    )
    prompt = build_screenshot_checklist_prompt(
        [finding], captions={"shot1.png": "Boss fight in the caverns"}
    )
    assert "shot1.png" in prompt
    assert "Boss fight in the caverns" in prompt
    assert "1920x1080" in prompt
    # No raw bytes are ever passed in — only structured text/numbers.
    assert isinstance(prompt, str)


def test_analyze_raises_when_provider_not_ready(tmp_path):
    db = Database(":memory:")
    service = TrailerScreenshotChecklistService(ScreenshotChecklistReportRepository(db))
    findings = scan_screenshots([_save_busy(tmp_path, "one.png")])
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), findings)


def test_analyze_saves_report_when_project_given(tmp_path):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = TrailerScreenshotChecklistService(ScreenshotChecklistReportRepository(db))
    findings = scan_screenshots([_save_busy(tmp_path, "one.png")])

    result = service.analyze(FakeProvider(), findings, project=project)

    assert result.response_text == CANNED
    assert result.report is not None
    history = service.history(project.id)
    assert len(history) == 1
    assert len(history[0].findings) == 1
