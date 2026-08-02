import json

import pytest

from spiced.core.accessibility_parser import (
    FORMAT_JSON,
    FORMAT_TEXT,
    contrast_ratio,
    parse_accessibility_data,
)


def test_black_on_white_is_maximum_contrast():
    assert contrast_ratio((0, 0, 0), (1, 1, 1)) == pytest.approx(21, rel=1e-3)


def test_identical_colors_have_contrast_of_one():
    assert contrast_ratio((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)) == pytest.approx(1, rel=1e-6)


def test_order_of_arguments_does_not_matter():
    a = contrast_ratio((0, 0, 0), (1, 1, 1))
    b = contrast_ratio((1, 1, 1), (0, 0, 0))
    assert a == pytest.approx(b)


def test_non_json_input_has_no_checklist():
    parsed = parse_accessibility_data("just some free-text notes about accessibility")
    assert parsed.source_format == FORMAT_TEXT
    assert parsed.contrast_checks == []
    assert parsed.score is None


def test_good_contrast_element_passes():
    payload = json.dumps(
        {"hud_elements": [{"name": "HealthBar", "foreground": "#FFFFFF", "background": "#000000"}]}
    )
    parsed = parse_accessibility_data(payload)
    assert parsed.source_format == FORMAT_JSON
    assert parsed.contrast_checks[0].passes is True
    assert not any(f.check == "contrast" for f in parsed.findings)


def test_poor_contrast_element_fails_and_is_flagged():
    payload = json.dumps(
        {"hud_elements": [{"name": "Subtitle", "foreground": "#333333", "background": "#000000"}]}
    )
    parsed = parse_accessibility_data(payload)
    assert parsed.contrast_checks[0].passes is False
    assert any(f.check == "contrast" for f in parsed.findings)


def test_red_green_pairing_flagged_by_colorblind_simulation():
    # High raw contrast but relies entirely on red-vs-green hue, a classic
    # colorblind-unsafe pairing.
    payload = json.dumps(
        {
            "hud_elements": [
                {"name": "TeamIndicator", "foreground": "#FF0000", "background": "#00FF00"}
            ]
        }
    )
    parsed = parse_accessibility_data(payload)
    check = parsed.contrast_checks[0]
    assert check.colorblind_safe is False
    assert any(f.check == "colorblind" for f in parsed.findings)


def test_caption_coverage_computed():
    payload = json.dumps(
        {
            "audio_files": [
                {"name": "a.wav", "captioned": True},
                {"name": "b.wav", "captioned": False},
                {"name": "c.wav", "captioned": False},
            ]
        }
    )
    parsed = parse_accessibility_data(payload)
    assert parsed.caption_total == 3
    assert parsed.caption_covered == 1
    assert parsed.caption_coverage_pct == pytest.approx(33.3, abs=0.1)
    assert any(f.check == "captions" for f in parsed.findings)


def test_controls_and_text_scaling_flags():
    payload = json.dumps({"controls_remappable": False, "text_scaling_supported": True})
    parsed = parse_accessibility_data(payload)
    assert parsed.controls_remappable is False
    assert parsed.text_scaling_supported is True
    assert any(f.check == "controls" for f in parsed.findings)
    assert not any(f.check == "text_scaling" for f in parsed.findings)


def test_score_is_average_of_available_checks():
    payload = json.dumps(
        {
            "hud_elements": [{"name": "HP", "foreground": "#FFFFFF", "background": "#000000"}],
            "controls_remappable": True,
            "text_scaling_supported": True,
        }
    )
    parsed = parse_accessibility_data(payload)
    assert parsed.score == 100


def test_malformed_json_falls_back_to_text():
    parsed = parse_accessibility_data("{not valid json")
    assert parsed.source_format == FORMAT_TEXT
