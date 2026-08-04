"""Tests for connectors.unity_scan: recursive, read-only Assets/ scans.

Builds small fake Unity-project directory trees under tmp_path — no real
Unity project or engine is ever needed.
"""

from __future__ import annotations

from spiced.connectors.unity_scan import (
    OVERSIZED_AUDIO_BYTES,
    OVERSIZED_TEXTURE_BYTES,
    find_oversized_and_uncompressed,
    infer_naming_convention,
    iter_assets,
    scan_references,
)


def _write_bytes(path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


def _write_meta(asset_path, guid: str) -> None:
    meta_path = asset_path.parent / (asset_path.name + ".meta")
    meta_path.write_text(f"fileFormatVersion: 2\nguid: {guid}\n", encoding="utf-8")


# --- iter_assets ---------------------------------------------------------------


def test_iter_assets_returns_empty_list_when_no_assets_folder(tmp_path):
    assert iter_assets(tmp_path) == []


def test_iter_assets_excludes_meta_files(tmp_path):
    asset = tmp_path / "Assets" / "Textures" / "hero.png"
    _write_bytes(asset, 10)
    _write_meta(asset, "a" * 32)
    found = iter_assets(tmp_path)
    assert asset in found
    assert not any(p.suffix == ".meta" for p in found)


# --- find_oversized_and_uncompressed -------------------------------------------


def test_flags_oversized_uncompressed_texture(tmp_path):
    big_png = tmp_path / "Assets" / "Textures" / "background.png"
    _write_bytes(big_png, OVERSIZED_TEXTURE_BYTES + 1)
    findings = find_oversized_and_uncompressed(tmp_path)
    assert len(findings) == 1
    assert findings[0].kind == "texture"
    assert findings[0].path == "Assets/Textures/background.png"


def test_does_not_flag_small_texture(tmp_path):
    small_png = tmp_path / "Assets" / "Textures" / "icon.png"
    _write_bytes(small_png, 1024)
    assert find_oversized_and_uncompressed(tmp_path) == []


def test_does_not_flag_compressed_texture_format_even_when_large(tmp_path):
    big_jpg = tmp_path / "Assets" / "Textures" / "background.jpg"
    _write_bytes(big_jpg, OVERSIZED_TEXTURE_BYTES + 1)
    assert find_oversized_and_uncompressed(tmp_path) == []


def test_flags_oversized_uncompressed_audio(tmp_path):
    big_wav = tmp_path / "Assets" / "Audio" / "theme.wav"
    _write_bytes(big_wav, OVERSIZED_AUDIO_BYTES + 1)
    findings = find_oversized_and_uncompressed(tmp_path)
    assert len(findings) == 1
    assert findings[0].kind == "audio"


def test_does_not_flag_compressed_audio_format_even_when_large(tmp_path):
    big_ogg = tmp_path / "Assets" / "Audio" / "theme.ogg"
    _write_bytes(big_ogg, OVERSIZED_AUDIO_BYTES + 1)
    assert find_oversized_and_uncompressed(tmp_path) == []


def test_findings_sorted_largest_first(tmp_path):
    small = tmp_path / "Assets" / "a.png"
    large = tmp_path / "Assets" / "b.png"
    _write_bytes(small, OVERSIZED_TEXTURE_BYTES + 100)
    _write_bytes(large, OVERSIZED_TEXTURE_BYTES + 10_000)
    findings = find_oversized_and_uncompressed(tmp_path)
    assert [f.path for f in findings] == ["Assets/b.png", "Assets/a.png"]


# --- scan_references (broken + orphaned) ---------------------------------------


def test_scan_references_empty_project_returns_empty_result(tmp_path):
    result = scan_references(tmp_path)
    assert result.broken_references == []
    assert result.orphaned_assets == []
    assert result.total_meta_files == 0


def test_scan_references_finds_a_valid_reference_no_false_positives(tmp_path):
    prefab_guid = "1" * 32
    prefab = tmp_path / "Assets" / "Prefabs" / "Player.prefab"
    _write_bytes(prefab, 10)
    _write_meta(prefab, prefab_guid)

    scene = tmp_path / "Assets" / "Scenes" / "Main.unity"
    scene.parent.mkdir(parents=True, exist_ok=True)
    scene.write_text(f"--- !u!1 &1\nm_Prefab: {{fileID: 100100000, guid: {prefab_guid}}}\n")
    _write_meta(scene, "2" * 32)

    result = scan_references(tmp_path)
    assert result.broken_references == []
    # The prefab is referenced by the scene, so it must not show as orphaned
    # (the scene itself isn't referenced by anything, which is normal — Unity
    # scenes are added to Build Settings by path, not by GUID reference).
    assert "Assets/Prefabs/Player.prefab" not in result.orphaned_assets


def test_scan_references_flags_broken_reference(tmp_path):
    scene = tmp_path / "Assets" / "Scenes" / "Main.unity"
    scene.parent.mkdir(parents=True, exist_ok=True)
    # High-entropy guid so it isn't mistaken for one of Unity's own
    # built-in-resource guids (see test_scan_references_ignores_builtin_...).
    missing_guid = "deadbeefdeadbeefdeadbeefdeadbeef"
    scene.write_text(f"m_Script: {{fileID: 11500000, guid: {missing_guid}, type: 3}}\n")
    _write_meta(scene, "2" * 32)

    result = scan_references(tmp_path)
    assert len(result.broken_references) == 1
    assert result.broken_references[0].missing_guid == missing_guid
    assert result.broken_references[0].referencing_file == "Assets/Scenes/Main.unity"


def test_scan_references_flags_orphaned_asset(tmp_path):
    unused = tmp_path / "Assets" / "Prefabs" / "Unused.prefab"
    _write_bytes(unused, 10)
    _write_meta(unused, "3" * 32)

    result = scan_references(tmp_path)
    assert result.orphaned_assets == ["Assets/Prefabs/Unused.prefab"]


def test_scan_references_excludes_resources_folder_from_orphan_flag(tmp_path):
    dynamically_loaded = tmp_path / "Assets" / "Resources" / "Icon.png"
    _write_bytes(dynamically_loaded, 10)
    _write_meta(dynamically_loaded, "4" * 32)

    result = scan_references(tmp_path)
    assert result.orphaned_assets == []


def test_scan_references_ignores_builtin_looking_guids(tmp_path):
    scene = tmp_path / "Assets" / "Scenes" / "Main.unity"
    scene.parent.mkdir(parents=True, exist_ok=True)
    # A Unity built-in-style guid: mostly one repeated digit.
    builtin_guid = "0" * 31 + "1"
    scene.write_text(f"m_Material: {{fileID: 2100000, guid: {builtin_guid}, type: 2}}\n")
    _write_meta(scene, "2" * 32)

    result = scan_references(tmp_path)
    assert result.broken_references == []


def test_scan_references_caveat_mentions_dynamic_loading():
    from spiced.connectors.unity_scan import ReferenceScanResult

    assert "Resources.Load" in ReferenceScanResult().caveat
    assert "Addressables" in ReferenceScanResult().caveat


# --- infer_naming_convention ----------------------------------------------------


def test_infer_naming_convention_no_assets_returns_none(tmp_path):
    result = infer_naming_convention(tmp_path)
    assert result.dominant_convention is None


def test_infer_naming_convention_detects_dominant_snake_case(tmp_path):
    for name in ["player_controller.cs", "enemy_spawner.cs", "health_bar.cs", "PascalOutlier.cs"]:
        _write_bytes(tmp_path / "Assets" / "Scripts" / name, 10)
    result = infer_naming_convention(tmp_path)
    assert result.dominant_convention == "snake_case"
    assert "Assets/Scripts/PascalOutlier.cs" in result.outliers


def test_infer_naming_convention_detects_dominant_pascal_case(tmp_path):
    for name in ["PlayerController.cs", "EnemySpawner.cs", "HealthBar.cs", "snake_outlier.cs"]:
        _write_bytes(tmp_path / "Assets" / "Scripts" / name, 10)
    result = infer_naming_convention(tmp_path)
    assert result.dominant_convention == "PascalCase"
    assert "Assets/Scripts/snake_outlier.cs" in result.outliers


def test_infer_naming_convention_counts_match_files(tmp_path):
    for name in ["a.cs", "b.cs", "c.cs"]:
        _write_bytes(tmp_path / "Assets" / name, 10)
    result = infer_naming_convention(tmp_path)
    assert result.total_files == 3
    assert result.total_classified == 3
    assert sum(result.convention_counts.values()) == 3
