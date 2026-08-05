"""Tests for core.asset_review_queue: Pillow-based checks + .meta text
introspection, built against tiny synthetic images/meta files under tmp_path."""

from __future__ import annotations

from PIL import Image

from spiced.core.asset_review_queue import (
    AssetReviewQueueService,
    review_asset,
    review_folder,
    review_paths,
)
from spiced.storage.asset_review_reports import AssetReviewReportRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

_TEXTURE_META_MIPMAPS_ENABLED = """fileFormatVersion: 2
guid: dcfda5a0b6ea04ccfab148149ab12d4a
TextureImporter:
  serializedVersion: 4
  mipmaps:
    mipMapMode: 0
    enableMipMap: 1
    sRGBTexture: 0
"""

_TEXTURE_META_MIPMAPS_DISABLED = """fileFormatVersion: 2
guid: dcfda5a0b6ea04ccfab148149ab12d4a
TextureImporter:
  serializedVersion: 4
  mipmaps:
    mipMapMode: 0
    enableMipMap: 0
    sRGBTexture: 0
"""


def _make_png(path, size=(64, 64), color=(255, 0, 0)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def test_power_of_two_texture_not_flagged(tmp_path):
    asset = tmp_path / "hero.png"
    _make_png(asset, size=(64, 64))
    finding = review_asset(asset)
    assert finding.is_power_of_two is True
    assert not any("power-of-two" in issue for issue in finding.issues)


def test_non_power_of_two_texture_flagged_as_heads_up(tmp_path):
    asset = tmp_path / "hero.png"
    _make_png(asset, size=(100, 70))
    finding = review_asset(asset)
    assert finding.is_power_of_two is False
    assert any("power-of-two" in issue for issue in finding.issues)


def test_source_only_format_flagged(tmp_path):
    asset = tmp_path / "hero.psd"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"\0" * 100)
    finding = review_asset(asset)
    assert finding.format_warning is not None
    assert "source-only" in finding.format_warning


def test_missing_meta_file_flagged_under_project_assets(tmp_path):
    asset = tmp_path / "Assets" / "Textures" / "hero.png"
    _make_png(asset)
    finding = review_asset(asset, project_root=tmp_path)
    assert finding.meta_present is False
    assert any(".meta" in issue for issue in finding.issues)


def test_meta_check_skipped_outside_project_assets(tmp_path):
    outside_root = tmp_path / "elsewhere"
    asset = outside_root / "hero.png"
    _make_png(asset)
    finding = review_asset(asset, project_root=tmp_path / "MyProject")
    assert finding.meta_present is None


def test_meta_present_with_mipmaps_enabled_not_flagged(tmp_path):
    asset = tmp_path / "Assets" / "Textures" / "hero.png"
    _make_png(asset)
    meta = asset.parent / (asset.name + ".meta")
    meta.write_text(_TEXTURE_META_MIPMAPS_ENABLED, encoding="utf-8")

    finding = review_asset(asset, project_root=tmp_path)
    assert finding.meta_present is True
    assert finding.meta_has_guid is True
    assert finding.mipmaps_enabled is True
    assert not any("Mipmaps are disabled" in issue for issue in finding.issues)


def test_meta_present_with_mipmaps_disabled_flagged(tmp_path):
    asset = tmp_path / "Assets" / "Textures" / "hero.png"
    _make_png(asset)
    meta = asset.parent / (asset.name + ".meta")
    meta.write_text(_TEXTURE_META_MIPMAPS_DISABLED, encoding="utf-8")

    finding = review_asset(asset, project_root=tmp_path)
    assert finding.mipmaps_enabled is False
    assert any("Mipmaps are disabled" in issue for issue in finding.issues)


def test_oversized_uncompressed_texture_flagged(tmp_path):
    asset = tmp_path / "big.png"
    asset.parent.mkdir(parents=True, exist_ok=True)
    # Not a real large image -- just a big file, which is all the size check needs.
    with open(asset, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(b"\0" * (5 * 1024 * 1024))
    finding = review_asset(asset)
    assert finding.oversized is True


def test_passed_is_true_when_no_issues(tmp_path):
    asset = tmp_path / "hero.png"
    _make_png(asset, size=(64, 64))
    finding = review_asset(asset)
    assert finding.passed is True
    assert finding.issues == []


def test_review_paths_reviews_each_path(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _make_png(a, size=(32, 32))
    _make_png(b, size=(50, 50))
    findings = review_paths([str(a), str(b)])
    assert len(findings) == 2


def test_service_review_saves_report_when_project_given(tmp_path):
    asset = tmp_path / "hero.png"
    _make_png(asset, size=(64, 64))
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = AssetReviewQueueService(AssetReviewReportRepository(db))

    result = service.review([str(asset)], project=project)
    assert len(result.findings) == 1
    history = service.history(project.id)
    assert len(history) == 1
    assert len(history[0].findings) == 1


def test_review_folder_walks_recursively_and_skips_meta_files(tmp_path):
    _make_png(tmp_path / "a.png", size=(32, 32))
    _make_png(tmp_path / "sub" / "b.png", size=(32, 32))
    (tmp_path / "a.png.meta").write_text("guid: " + "a" * 32, encoding="utf-8")
    findings = review_folder(tmp_path)
    reviewed_names = {f.path for f in findings}
    assert len(findings) == 2
    assert not any(n.endswith(".meta") for n in reviewed_names)


def test_service_review_without_project_does_not_save(tmp_path):
    asset = tmp_path / "hero.png"
    _make_png(asset, size=(64, 64))
    db = Database(":memory:")
    service = AssetReviewQueueService(AssetReviewReportRepository(db))

    result = service.review([str(asset)], project=None)
    assert result.report is None
