"""Visual Regression Testing: pixel-diff detection for changed vs. unchanged pairs."""

from __future__ import annotations

from PIL import Image

from spiced.core.visual_regression import (
    CHANGE_RATIO_THRESHOLD,
    VisualRegressionService,
    diff_folders,
    diff_pair,
)
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.visual_regression_reports import VisualRegressionReportRepository


def _save_solid(path, color, size=(64, 64)):
    Image.new("RGB", size, color).save(path)


def _save_half_changed(path, size=(64, 64)):
    img = Image.new("RGB", size, (10, 10, 10))
    for x in range(size[0] // 2, size[0]):
        for y in range(size[1]):
            img.putpixel((x, y), (250, 250, 250))
    img.save(path)


def test_identical_pair_is_not_flagged(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    _save_solid(before, (100, 100, 100))
    _save_solid(after, (100, 100, 100))

    result = diff_pair(before, after)
    assert result.changed is False
    assert result.changed_pixel_ratio == 0.0


def test_clearly_changed_pair_is_flagged_and_diff_image_saved(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    _save_solid(before, (10, 10, 10))
    _save_solid(after, (250, 250, 250))

    diff_out = tmp_path / "diff.png"
    result = diff_pair(before, after, save_diff_to=diff_out)
    assert result.changed is True
    assert result.changed_pixel_ratio > CHANGE_RATIO_THRESHOLD
    assert diff_out.exists()


def test_effectively_identical_pair_with_tiny_noise_is_not_flagged(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    img = Image.new("RGB", (64, 64), (128, 128, 128))
    img.save(before)
    # Nudge a single pixel slightly -- below the per-pixel threshold and far
    # below the overall changed-ratio threshold.
    img2 = img.copy()
    img2.putpixel((0, 0), (130, 130, 130))
    img2.save(after)

    result = diff_pair(before, after)
    assert result.changed is False


def test_diff_folders_matches_by_filename_and_lists_unmatched(tmp_path):
    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    before_dir.mkdir()
    after_dir.mkdir()

    _save_solid(before_dir / "scene1.png", (10, 10, 10))
    _save_solid(after_dir / "scene1.png", (250, 250, 250))
    _save_solid(before_dir / "scene2.png", (50, 50, 50))
    _save_solid(after_dir / "scene2.png", (50, 50, 50))
    _save_solid(before_dir / "only_before.png", (1, 1, 1))
    _save_solid(after_dir / "only_after.png", (2, 2, 2))

    result = diff_folders(before_dir, after_dir)
    assert len(result.pairs) == 2
    assert result.unmatched_before == ["only_before.png"]
    assert result.unmatched_after == ["only_after.png"]
    assert result.changed_count == 1
    changed_names = {p.name for p in result.pairs if p.changed}
    assert changed_names == {"scene1.png"}


def test_size_mismatch_is_recorded(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    _save_solid(before, (10, 10, 10), size=(64, 64))
    _save_solid(after, (10, 10, 10), size=(32, 32))

    result = diff_pair(before, after)
    assert result.size_mismatch is True


def test_service_diff_persists_report_and_history(tmp_path):
    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    before_dir.mkdir()
    after_dir.mkdir()
    _save_solid(before_dir / "a.png", (10, 10, 10))
    _save_solid(after_dir / "a.png", (250, 250, 250))

    db = Database(":memory:")
    project = ProjectRepository(db).create("Demo")
    service = VisualRegressionService(VisualRegressionReportRepository(db))

    result, report = service.diff(project, before_dir, after_dir)
    assert result.changed_count == 1
    assert report is not None
    assert report.findings["changed_count"] == 1
    assert len(service.history(project.id)) == 1
