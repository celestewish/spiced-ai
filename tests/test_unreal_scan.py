"""Tests for connectors.unreal_scan."""

from __future__ import annotations

from spiced.connectors.unreal_scan import (
    find_loose_uncompressed_source_assets,
    find_oversized_binary_assets,
    iter_content_files,
)


def test_iter_content_files_empty_without_content_folder(tmp_path):
    assert iter_content_files(tmp_path) == []


def test_iter_content_files_lists_everything_under_content(tmp_path):
    content = tmp_path / "Content"
    content.mkdir()
    (content / "Character.uasset").write_bytes(b"\x00")
    sub = content / "Maps"
    sub.mkdir()
    (sub / "Level.umap").write_bytes(b"\x00")

    files = {p.relative_to(tmp_path).as_posix() for p in iter_content_files(tmp_path)}
    assert files == {"Content/Character.uasset", "Content/Maps/Level.umap"}


def test_find_oversized_binary_assets_flags_large_uasset(tmp_path):
    content = tmp_path / "Content"
    content.mkdir()
    (content / "BigMesh.uasset").write_bytes(b"\x00" * (25 * 1024 * 1024))

    findings = find_oversized_binary_assets(tmp_path)

    assert len(findings) == 1
    assert findings[0].path == "Content/BigMesh.uasset"
    assert findings[0].kind == "uasset"


def test_find_oversized_binary_assets_flags_large_umap_with_its_own_threshold(tmp_path):
    content = tmp_path / "Content"
    content.mkdir()
    # Below the .uasset threshold but above the (higher) .umap threshold.
    (content / "MainLevel.umap").write_bytes(b"\x00" * (55 * 1024 * 1024))

    findings = find_oversized_binary_assets(tmp_path)

    assert len(findings) == 1
    assert findings[0].kind == "umap"


def test_find_oversized_binary_assets_ignores_small_files(tmp_path):
    content = tmp_path / "Content"
    content.mkdir()
    (content / "Small.uasset").write_bytes(b"\x00" * 100)

    assert find_oversized_binary_assets(tmp_path) == []


def test_find_oversized_binary_assets_ignores_non_binary_extensions(tmp_path):
    content = tmp_path / "Content"
    content.mkdir()
    # A large file that isn't .uasset/.umap shouldn't be flagged by this scan.
    (content / "readme.txt").write_bytes(b"\x00" * (25 * 1024 * 1024))

    assert find_oversized_binary_assets(tmp_path) == []


def test_find_loose_uncompressed_source_assets_flags_large_png(tmp_path):
    content = tmp_path / "Content"
    content.mkdir()
    (content / "concept_art.png").write_bytes(b"\x00" * (5 * 1024 * 1024))

    findings = find_loose_uncompressed_source_assets(tmp_path)

    assert len(findings) == 1
    assert findings[0].kind == "texture"
    assert "hasn't been imported" in findings[0].reason


def test_find_loose_uncompressed_source_assets_flags_large_wav(tmp_path):
    content = tmp_path / "Content"
    content.mkdir()
    (content / "voice_line.wav").write_bytes(b"\x00" * (6 * 1024 * 1024))

    findings = find_loose_uncompressed_source_assets(tmp_path)

    assert len(findings) == 1
    assert findings[0].kind == "audio"


def test_find_loose_uncompressed_source_assets_ignores_uasset_files(tmp_path):
    content = tmp_path / "Content"
    content.mkdir()
    (content / "Texture.uasset").write_bytes(b"\x00" * (10 * 1024 * 1024))

    assert find_loose_uncompressed_source_assets(tmp_path) == []
