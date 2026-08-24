"""Tests for connectors.godot_scan.

The ``.import`` sidecar sample below is a trimmed, faithful reproduction of
a real Godot-generated ``.import`` file (fetched from ``godotengine/godot-
demo-projects``, ``2d/dodge_the_creeps/icon.webp.import``, during
development to verify field names/layout -- see the module's docstring).
"""

from __future__ import annotations

from spiced.connectors.godot_scan import (
    find_oversized_and_uncompressed,
    iter_resources,
    scan_imports,
)

ICON_IMPORT_TEXT = """[remap]

importer="texture"
type="CompressedTexture2D"
uid="uid://dfklrdtaun0xt"
path="res://.godot/imported/icon.webp-e94f9a68b0f625a567a797079e4d325f.ctex"
metadata={
"vram_texture": false
}

[deps]

source_file="res://icon.webp"
dest_files=["res://.godot/imported/icon.webp-e94f9a68b0f625a567a797079e4d325f.ctex"]

[params]

compress/mode=0
"""


def test_iter_resources_excludes_godot_and_git_dirs(tmp_path):
    (tmp_path / "player.gd").write_text("extends Node2D\n", encoding="utf-8")
    godot_dir = tmp_path / ".godot" / "imported"
    godot_dir.mkdir(parents=True)
    (godot_dir / "icon.webp-abc123.ctex").write_bytes(b"\x00")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    resources = iter_resources(tmp_path)

    rel_paths = {p.relative_to(tmp_path).as_posix() for p in resources}
    assert rel_paths == {"player.gd"}


def test_iter_resources_excludes_import_sidecar_files(tmp_path):
    (tmp_path / "icon.webp").write_bytes(b"\x00" * 10)
    (tmp_path / "icon.webp.import").write_text(ICON_IMPORT_TEXT, encoding="utf-8")

    resources = iter_resources(tmp_path)

    rel_paths = {p.relative_to(tmp_path).as_posix() for p in resources}
    assert rel_paths == {"icon.webp"}


def test_iter_resources_empty_for_missing_folder(tmp_path):
    assert iter_resources(tmp_path / "nope") == []


def test_find_oversized_and_uncompressed_flags_large_png(tmp_path):
    big_png = tmp_path / "art" / "background.png"
    big_png.parent.mkdir()
    big_png.write_bytes(b"\x00" * (5 * 1024 * 1024))

    findings = find_oversized_and_uncompressed(tmp_path)

    assert len(findings) == 1
    assert findings[0].path == "art/background.png"
    assert findings[0].kind == "texture"


def test_find_oversized_and_uncompressed_ignores_small_files(tmp_path):
    (tmp_path / "icon.png").write_bytes(b"\x00" * 100)

    assert find_oversized_and_uncompressed(tmp_path) == []


def test_find_oversized_and_uncompressed_flags_large_wav(tmp_path):
    big_wav = tmp_path / "music.wav"
    big_wav.write_bytes(b"\x00" * (6 * 1024 * 1024))

    findings = find_oversized_and_uncompressed(tmp_path)

    assert len(findings) == 1
    assert findings[0].kind == "audio"


def test_scan_imports_flags_not_yet_imported_resource(tmp_path):
    (tmp_path / "icon.webp").write_bytes(b"\x00" * 10)
    # No icon.webp.import sidecar written -- not yet imported.

    result = scan_imports(tmp_path)

    assert result.not_yet_imported == ["icon.webp"]
    assert result.orphaned_import_files == []


def test_scan_imports_does_not_flag_properly_imported_resource(tmp_path):
    (tmp_path / "icon.webp").write_bytes(b"\x00" * 10)
    (tmp_path / "icon.webp.import").write_text(ICON_IMPORT_TEXT, encoding="utf-8")

    result = scan_imports(tmp_path)

    assert result.not_yet_imported == []
    assert result.orphaned_import_files == []


def test_scan_imports_flags_orphaned_import_sidecar(tmp_path):
    # The .import sidecar exists, but its source_file (icon.webp) was
    # deleted or renamed outside the editor.
    (tmp_path / "icon.webp.import").write_text(ICON_IMPORT_TEXT, encoding="utf-8")

    result = scan_imports(tmp_path)

    assert result.orphaned_import_files == ["icon.webp.import"]
    assert result.not_yet_imported == []


def test_scan_imports_empty_for_missing_folder(tmp_path):
    result = scan_imports(tmp_path / "nope")
    assert result.not_yet_imported == []
    assert result.orphaned_import_files == []
