"""Tests for automation.palette_drift (Implementation Bible, Feature 4). No
mocking needed -- everything (k-means, Lab conversion, Delta-E, BatchRunner)
runs for real against tiny synthetic Pillow images, matching the Bible's own
acceptance criteria: a wildly-different-palette asset gets flagged, a
near-identical one doesn't."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from spiced.automation import palette_drift as pd
from spiced.automation.finding import STATUS_FLAGGED, STATUS_PASS
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.palette_reference_colors import PaletteReferenceColorRepository
from spiced.storage.projects import ProjectRepository


def _solid_png(path, color, size=(40, 40)):
    Image.new("RGB", size, color=color).save(path)


BLUE = (30, 60, 200)
NEAR_BLUE = (35, 65, 195)
ORANGE = (255, 140, 0)


# --- hex helpers ------------------------------------------------------------


def test_normalize_hex_color_accepts_with_or_without_hash():
    assert pd.normalize_hex_color("#3366CC") == "#3366cc"
    assert pd.normalize_hex_color("3366CC") == "#3366cc"


def test_normalize_hex_color_rejects_invalid():
    with pytest.raises(ValueError):
        pd.normalize_hex_color("not-a-color")
    with pytest.raises(ValueError):
        pd.normalize_hex_color("#fff")  # 3-digit shorthand not supported


def test_hex_rgb_round_trip():
    assert pd._rgb_to_hex(pd._hex_to_rgb("#3366cc")) == "#3366cc"


# --- rgb_to_lab / delta_e_cie76 --------------------------------------------


def test_rgb_to_lab_black_and_white_are_extremes():
    black_l = pd.rgb_to_lab((0, 0, 0))[0]
    white_l = pd.rgb_to_lab((255, 255, 255))[0]
    assert black_l == pytest.approx(0.0, abs=0.5)
    assert white_l == pytest.approx(100.0, abs=0.5)


def test_delta_e_identical_colors_is_zero():
    lab = pd.rgb_to_lab((100, 150, 200))
    assert pd.delta_e_cie76(lab, lab) == pytest.approx(0.0, abs=1e-6)


def test_delta_e_black_white_is_large():
    delta = pd.delta_e_cie76(pd.rgb_to_lab((0, 0, 0)), pd.rgb_to_lab((255, 255, 255)))
    assert delta > 50


# --- extract_dominant_colors / average_nearest_delta_e ----------------------


def test_extract_dominant_colors_solid_image_returns_that_color(tmp_path):
    p = tmp_path / "solid.png"
    _solid_png(p, BLUE)

    colors = pd.extract_dominant_colors(p, k=4)

    assert len(colors) == 4
    for c in colors:
        rgb = pd._hex_to_rgb(c)
        assert all(abs(rgb[i] - BLUE[i]) <= 2 for i in range(3))


def test_extract_dominant_colors_unreadable_file_raises(tmp_path):
    bad = tmp_path / "not_an_image.png"
    bad.write_text("not an image", encoding="utf-8")
    with pytest.raises(pd.UnreadableImageError):
        pd.extract_dominant_colors(bad)


def test_average_nearest_delta_e_identical_palettes_is_zero():
    palette = ["#1e3cc8", "#ff8c00"]
    assert pd.average_nearest_delta_e(palette, palette) == pytest.approx(0.0, abs=1e-6)


def test_average_nearest_delta_e_empty_inputs():
    assert pd.average_nearest_delta_e([], ["#ffffff"]) == 0.0
    assert pd.average_nearest_delta_e(["#ffffff"], []) == 0.0


# --- check_palette_drift (Bible acceptance criteria) -----------------------


def test_check_palette_drift_near_identical_not_flagged(tmp_path):
    p = tmp_path / "OnStyle.png"
    _solid_png(p, NEAR_BLUE)

    item = pd.check_palette_drift(p, reference_colors=["#" + "".join(f"{c:02x}" for c in BLUE)])

    assert item.severity == "info"
    assert item.detail["delta_e_avg"] < pd.DEFAULT_DELTA_E_THRESHOLD


def test_check_palette_drift_wildly_different_is_flagged(tmp_path):
    p = tmp_path / "OffStyle.png"
    _solid_png(p, ORANGE)

    item = pd.check_palette_drift(p, reference_colors=["#" + "".join(f"{c:02x}" for c in BLUE)])

    assert item.severity == "warning"
    assert item.detail["delta_e_avg"] > pd.DEFAULT_DELTA_E_THRESHOLD
    assert "flagged" in item.message


# --- scan_folder_for_drift (BatchRunner wiring) -----------------------------


def test_scan_folder_for_drift_no_reference_raises(tmp_path):
    with pytest.raises(pd.NoReferencePaletteError):
        pd.scan_folder_for_drift(tmp_path, [], project_id="1")


def test_scan_folder_for_drift_flags_and_passes_correctly(tmp_path):
    ref_hex = "#" + "".join(f"{c:02x}" for c in BLUE)
    _solid_png(tmp_path / "OnStyle.png", NEAR_BLUE)
    _solid_png(tmp_path / "OffStyle.png", ORANGE)
    (tmp_path / "notes.txt").write_text("not an image", encoding="utf-8")

    finding = pd.scan_folder_for_drift(tmp_path, [ref_hex], project_id="1")

    assert finding.status == STATUS_FLAGGED
    by_name = {i.asset_path.split("\\")[-1].split("/")[-1]: i for i in finding.items}
    assert by_name["OnStyle.png"].severity == "info"
    assert by_name["OffStyle.png"].severity == "warning"
    assert "notes.txt" not in by_name  # non-image extension filtered out


def test_scan_folder_for_drift_all_on_style_passes(tmp_path):
    ref_hex = "#" + "".join(f"{c:02x}" for c in BLUE)
    _solid_png(tmp_path / "a.png", BLUE)
    _solid_png(tmp_path / "b.png", NEAR_BLUE)

    finding = pd.scan_folder_for_drift(tmp_path, [ref_hex], project_id="1")

    assert finding.status == STATUS_PASS


# --- combined_reference_palette --------------------------------------------


def test_combined_reference_palette_no_images_raises(tmp_path):
    with pytest.raises(pd.NoReferencePaletteError):
        pd.combined_reference_palette(tmp_path)


def test_combined_reference_palette_not_a_folder_raises(tmp_path):
    with pytest.raises(pd.NoReferencePaletteError):
        pd.combined_reference_palette(tmp_path / "does_not_exist")


def test_combined_reference_palette_extracts_representative_colors(tmp_path):
    _solid_png(tmp_path / "a.png", BLUE)
    _solid_png(tmp_path / "b.png", NEAR_BLUE)

    colors = pd.combined_reference_palette(tmp_path, k=4)

    assert len(colors) == 4
    for c in colors:
        rgb = pd._hex_to_rgb(c)
        assert all(abs(rgb[i] - BLUE[i]) <= 5 for i in range(3))


# --- PaletteDriftService ----------------------------------------------------


def _setup_service():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    reference = PaletteReferenceColorRepository(db)
    findings = AutomationFindingRepository(db)
    service = pd.PaletteDriftService(reference, findings)
    project = projects.create("Moonlit Depths")
    return service, projects, project


def test_service_add_list_remove_reference_colors():
    service, _projects, project = _setup_service()
    color = service.add_reference_color(project.id, "#3366CC")
    assert service.list_reference_colors(project.id) == [color]
    service.remove_reference_color(color.id)
    assert service.list_reference_colors(project.id) == []


def test_service_set_reference_from_folder_replaces_existing(tmp_path):
    service, _projects, project = _setup_service()
    service.add_reference_color(project.id, "#ffffff")
    _solid_png(tmp_path / "a.png", BLUE)

    records = service.set_reference_from_folder(project.id, tmp_path, k=2)

    current = service.list_reference_colors(project.id)
    assert current == records
    assert "#ffffff" not in {r.hex_color for r in current}


def test_service_scan_raises_without_reference(tmp_path):
    service, projects, project = _setup_service()
    with pytest.raises(pd.NoReferencePaletteError):
        service.scan(project, tmp_path)


def test_service_scan_persists_finding_and_history(tmp_path):
    service, projects, project = _setup_service()
    service.add_reference_color(project.id, "#" + "".join(f"{c:02x}" for c in BLUE))
    _solid_png(tmp_path / "OnStyle.png", NEAR_BLUE)

    finding, record = service.scan(project, tmp_path)

    assert record.feature_id == pd.FEATURE_ID
    assert service.history(project.id) == [record]


def test_service_scan_uses_project_threshold(tmp_path):
    service, projects, project = _setup_service()
    service.add_reference_color(project.id, "#" + "".join(f"{c:02x}" for c in BLUE))
    project = projects.set_palette_drift_threshold(project.id, 1000.0)  # absurdly high
    _solid_png(tmp_path / "OffStyle.png", ORANGE)

    finding, _record = service.scan(project, tmp_path)

    assert finding.status == STATUS_PASS  # even the orange asset passes under this threshold


# --- CLI ---------------------------------------------------------------


def test_cli_scans_and_prints_summary(tmp_path, capsys):
    ref_hex = "#" + "".join(f"{c:02x}" for c in BLUE)
    _solid_png(tmp_path / "OnStyle.png", NEAR_BLUE)

    exit_code = pd._cli([str(tmp_path), "--reference-colors", ref_hex])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no palette drift found" in out


def test_cli_json_flag(tmp_path, capsys):
    ref_hex = "#" + "".join(f"{c:02x}" for c in BLUE)
    _solid_png(tmp_path / "OnStyle.png", NEAR_BLUE)

    exit_code = pd._cli([str(tmp_path), "--reference-colors", ref_hex, "--json"])

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert exit_code == 0
    assert parsed["feature_id"] == pd.FEATURE_ID


def test_cli_requires_reference_colors(tmp_path):
    with pytest.raises(SystemExit):
        pd._cli([str(tmp_path)])
