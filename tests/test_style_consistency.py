"""Tests for core.style_consistency: statistical outlier detection against a
small crafted asset population, using synthetic Pillow images."""

from __future__ import annotations

import pytest
from PIL import Image

from spiced.core.style_consistency import (
    UnreadableImageError,
    check_style_consistency,
    scan_population_for_outliers,
)


def _make_png(path, size=(64, 64), color=(20, 30, 200)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def test_new_asset_matching_population_is_not_flagged(tmp_path):
    population = []
    for i in range(4):
        p = tmp_path / f"pop_{i}.png"
        _make_png(p, size=(64, 64), color=(20, 30, 200))
        population.append(str(p))
    candidate = tmp_path / "candidate.png"
    _make_png(candidate, size=(64, 64), color=(22, 32, 198))

    result = check_style_consistency(candidate, population)
    assert result.outliers == []


def test_new_asset_with_outlier_resolution_is_flagged(tmp_path):
    population = []
    for i in range(4):
        p = tmp_path / f"pop_{i}.png"
        _make_png(p, size=(64, 64), color=(20, 30, 200))
        population.append(str(p))
    candidate = tmp_path / "candidate.png"
    _make_png(candidate, size=(1024, 1024), color=(20, 30, 200))

    result = check_style_consistency(candidate, population)
    assert len(result.outliers) == 1
    assert any("Width" in reason or "Height" in reason for reason in result.outliers[0].reasons)


def test_new_asset_with_outlier_color_is_flagged(tmp_path):
    population = []
    for i in range(4):
        p = tmp_path / f"pop_{i}.png"
        _make_png(p, size=(64, 64), color=(20, 30, 200))
        population.append(str(p))
    candidate = tmp_path / "candidate.png"
    _make_png(candidate, size=(64, 64), color=(240, 230, 10))

    result = check_style_consistency(candidate, population)
    assert len(result.outliers) == 1
    assert any("color" in reason.lower() for reason in result.outliers[0].reasons)


def test_unreadable_candidate_raises():
    fake = "does_not_exist.png"
    with pytest.raises(UnreadableImageError):
        check_style_consistency(fake, [])


def test_too_small_population_returns_no_outliers(tmp_path):
    p = tmp_path / "only_one.png"
    _make_png(p)
    candidate = tmp_path / "candidate.png"
    _make_png(candidate, size=(1000, 1000))
    result = check_style_consistency(candidate, [str(p)])
    assert result.outliers == []
    assert result.population_size == 1


def test_scan_population_for_outliers_leave_one_out(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"consistent_{i}.png"
        _make_png(p, size=(64, 64), color=(20, 30, 200))
        paths.append(str(p))
    outlier = tmp_path / "outlier.png"
    _make_png(outlier, size=(1024, 1024), color=(250, 5, 5))
    paths.append(str(outlier))

    result = scan_population_for_outliers(paths)
    outlier_paths = {o.path for o in result.outliers}
    # The single wild outlier is always flagged. Note: leave-one-out means a
    # lone extreme outlier can also skew *other* entries' averages enough to
    # get themselves flagged too (a real, documented limitation of comparing
    # against a small, non-robust population average) -- this test only
    # asserts the true outlier itself is caught, not that nothing else is.
    assert str(outlier) in outlier_paths
