"""Tests for ui.theme's In-App Accessibility Settings (Phase L, Core tier):
build_stylesheet's text-size/high-contrast/colorblind-safe variants, plus
Services' settings round-trip.
"""

from __future__ import annotations

from spiced.app.services import Services
from spiced.ui.theme import (
    COLORBLIND_SAFE_PALETTE,
    DEFAULT_PALETTE,
    HIGH_CONTRAST_PALETTE,
    STYLESHEET,
    TEXT_SIZES,
    build_stylesheet,
)


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


# --- build_stylesheet: text size -----------------------------------------------


def test_build_stylesheet_default_matches_module_level_stylesheet():
    assert build_stylesheet() == STYLESHEET


def test_build_stylesheet_small_text_uses_smaller_font_size_than_large():
    small = build_stylesheet(text_size="small")
    large = build_stylesheet(text_size="large")
    assert f"font-size: {TEXT_SIZES['small']}px;" in small
    assert f"font-size: {TEXT_SIZES['large']}px;" in large
    assert TEXT_SIZES["small"] < TEXT_SIZES["large"]


def test_build_stylesheet_unknown_text_size_falls_back_to_normal():
    sheet = build_stylesheet(text_size="not-a-real-size")
    assert f"font-size: {TEXT_SIZES['normal']}px;" in sheet


# --- build_stylesheet: high-contrast / colorblind-safe palettes --------------


def test_build_stylesheet_default_uses_default_palette_colors():
    sheet = build_stylesheet()
    assert DEFAULT_PALETTE["SAFFRON"] in sheet
    assert HIGH_CONTRAST_PALETTE["SAFFRON"] not in sheet


def test_build_stylesheet_high_contrast_actually_differs_from_default():
    default_sheet = build_stylesheet()
    contrast_sheet = build_stylesheet(high_contrast=True)
    assert default_sheet != contrast_sheet
    assert HIGH_CONTRAST_PALETTE["BROWN"] in contrast_sheet
    assert HIGH_CONTRAST_PALETTE["CREAM"] in contrast_sheet
    # Genuinely higher contrast, not a relabeling: near-black on white.
    assert HIGH_CONTRAST_PALETTE["BROWN"] == "#000000"
    assert HIGH_CONTRAST_PALETTE["CREAM"] == "#FFFFFF"


def test_build_stylesheet_colorblind_safe_actually_differs_from_default():
    default_sheet = build_stylesheet()
    cb_sheet = build_stylesheet(colorblind_safe=True)
    assert default_sheet != cb_sheet
    assert COLORBLIND_SAFE_PALETTE["SAFFRON"] in cb_sheet
    assert COLORBLIND_SAFE_PALETTE["SAFFRON"] != DEFAULT_PALETTE["SAFFRON"]


def test_build_stylesheet_high_contrast_wins_over_colorblind_safe_when_both_set():
    sheet = build_stylesheet(high_contrast=True, colorblind_safe=True)
    assert HIGH_CONTRAST_PALETTE["BROWN"] in sheet
    assert COLORBLIND_SAFE_PALETTE["SAFFRON"] not in sheet


def test_build_stylesheet_reduce_motion_accepted_without_error():
    """No animation exists to reduce (see ui.theme's module docstring) --
    this only confirms the parameter is accepted and doesn't change the
    stylesheet's own content, which is the honestly-documented current
    behavior, not an oversight."""
    without = build_stylesheet(reduce_motion=False)
    with_reduce = build_stylesheet(reduce_motion=True)
    assert without == with_reduce


# --- Services: accessibility settings round-trip -------------------------------


def test_accessibility_settings_default_off_and_normal_text(tmp_path):
    services = _services(tmp_path)
    assert services.accessibility_text_size() == "normal"
    assert services.accessibility_high_contrast_enabled() is False
    assert services.accessibility_colorblind_safe_enabled() is False
    assert services.accessibility_reduce_motion_enabled() is False


def test_accessibility_settings_round_trip(tmp_path):
    services = _services(tmp_path)
    services.set_accessibility_text_size("large")
    services.set_accessibility_high_contrast_enabled(True)
    services.set_accessibility_colorblind_safe_enabled(True)
    services.set_accessibility_reduce_motion_enabled(True)

    assert services.accessibility_text_size() == "large"
    assert services.accessibility_high_contrast_enabled() is True
    assert services.accessibility_colorblind_safe_enabled() is True
    assert services.accessibility_reduce_motion_enabled() is True

    services.set_accessibility_high_contrast_enabled(False)
    assert services.accessibility_high_contrast_enabled() is False
