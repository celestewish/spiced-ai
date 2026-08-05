"""Tests for core.placement_preview: the scoped-down Pillow composite mockup
(explicitly NOT a real in-engine render -- see the module docstring)."""

from __future__ import annotations

import pytest
from PIL import Image

from spiced.core.placement_preview import UnreadableImageError, create_placement_preview


def _make_png(path, size, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path)


def test_creates_composite_centered_by_default(tmp_path):
    bg = tmp_path / "bg.png"
    asset = tmp_path / "asset.png"
    out = tmp_path / "out.png"
    _make_png(bg, (200, 100), (10, 10, 10, 255))
    _make_png(asset, (40, 40), (255, 0, 0, 255))

    result = create_placement_preview(bg, asset, out)
    assert out.is_file()
    assert result.background_size == (200, 100)
    assert result.position == (80, 30)  # centered: (200-40)/2, (100-40)/2


def test_explicit_position_used_when_given(tmp_path):
    bg = tmp_path / "bg.png"
    asset = tmp_path / "asset.png"
    out = tmp_path / "out.png"
    _make_png(bg, (200, 100), (10, 10, 10, 255))
    _make_png(asset, (40, 40), (255, 0, 0, 255))

    result = create_placement_preview(bg, asset, out, x=5, y=10)
    assert result.position == (5, 10)


def test_scale_resizes_asset(tmp_path):
    bg = tmp_path / "bg.png"
    asset = tmp_path / "asset.png"
    out = tmp_path / "out.png"
    _make_png(bg, (200, 200), (10, 10, 10, 255))
    _make_png(asset, (40, 40), (255, 0, 0, 255))

    result = create_placement_preview(bg, asset, out, scale=2.0)
    assert result.asset_size_placed == (80, 80)


def test_unreadable_background_raises(tmp_path):
    asset = tmp_path / "asset.png"
    _make_png(asset, (40, 40), (255, 0, 0, 255))
    with pytest.raises(UnreadableImageError):
        create_placement_preview(tmp_path / "missing_bg.png", asset, tmp_path / "out.png")


def test_unreadable_asset_raises(tmp_path):
    bg = tmp_path / "bg.png"
    _make_png(bg, (200, 200), (10, 10, 10, 255))
    with pytest.raises(UnreadableImageError):
        create_placement_preview(bg, tmp_path / "missing_asset.png", tmp_path / "out.png")


def test_disclaimer_says_not_a_real_render(tmp_path):
    bg = tmp_path / "bg.png"
    asset = tmp_path / "asset.png"
    _make_png(bg, (200, 200), (10, 10, 10, 255))
    _make_png(asset, (40, 40), (255, 0, 0, 255))
    result = create_placement_preview(bg, asset, tmp_path / "out.png")
    assert "not a real" in result.disclaimer.lower()
