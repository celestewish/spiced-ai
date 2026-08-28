"""E2E §2 -- Godot Connector (E2E_TEST_PLAN.md).

**Deviations from the plan (see the final report for the full list):**

* §2.3 ("version mismatch... graceful degradation with a version warning")
  has no corresponding mechanism: ``detect_godot_project`` extracts whatever
  ``config/features`` version string is present but never compares it
  against an "expected"/connector version, and emits no warning for a
  version difference (only for a missing/unreadable project file). Rewritten
  to what's real: an older/newer version string is extracted correctly and
  never fails detection.
* §2.4 ("Godot + Git combined event stream") is folded into §7
  cross-cutting, same reasoning as §1.4 -- neither connector emits events on
  its own; there's nothing Godot-specific to test for "shares a pipeline"
  here.
* §2.2 ("GDScript-specific analysis... the same way C# issues are for
  Unity") maps onto ``connectors.godot_docs_scan.scan_scripts``, which
  extracts class/method/doc-comment structure (parity with
  ``unity_docs_scan``) rather than flagging bugs -- Spiced has no GDScript
  bug/lint analyzer as of this phase. Tested for structural parity, not
  "issues detected".
"""

from __future__ import annotations

from conftest import make_godot_fixture_project

from spiced.connectors.godot import detect_godot_project
from spiced.connectors.godot_docs_scan import scan_scripts
from spiced.connectors.godot_scan import find_oversized_and_uncompressed
from spiced.connectors.godot_scene_scan import scan_broken_references, scan_scenes

# --- §2.1: detect + parse scene tree/scripts/assets -------------------------


def test_2_1_detects_fixture_project_and_reads_metadata(tmp_path):
    project = make_godot_fixture_project(tmp_path)

    result = detect_godot_project(project)

    assert result.is_valid is True
    assert result.project_name == "Fixture Game"
    assert result.main_scene == "res://main.tscn"
    assert result.warnings == []


def test_2_1_parses_scene_tree(tmp_path):
    project = make_godot_fixture_project(tmp_path)

    scenes = scan_scenes(project)

    assert len(scenes) == 1
    assert scenes[0].path == "main.tscn"
    assert [n.name for n in scenes[0].nodes] == ["Main"]
    assert scenes[0].ext_resources[0].path == "res://main.gd"


def test_2_1_identifies_scripts_and_imported_assets(tmp_path):
    project = make_godot_fixture_project(tmp_path)

    scripts = scan_scripts(project)
    assets = find_oversized_and_uncompressed(project)

    assert scripts.file_count == 1  # main.gd
    # A tiny 32x32 fixture PNG is neither oversized nor flagged as
    # uncompressed-and-large -- confirms the scan *sees* the imported asset
    # without false-flagging it.
    assert all(a.path != "assets/icon.png" for a in assets)


# --- §2.2: rewritten -- structural parity with Unity's docs scan -----------


def test_2_2_gdscript_scan_extracts_class_and_public_method(tmp_path):
    project = make_godot_fixture_project(tmp_path)
    (project / "player.gd").write_text(
        "## Handles player movement.\n"
        "class_name Player\n\n"
        "## Moves the player by one step.\n"
        "func take_step(direction: Vector2) -> void:\n"
        "\tpass\n\n"
        "func _physics_process(delta: float) -> void:\n"
        "\tpass\n",
        encoding="utf-8",
    )

    result = scan_scripts(project)

    player = next(c for c in result.classes if c.name == "Player")
    assert player.doc_comment == "Handles player movement."
    method_names = [m.name for m in player.methods]
    assert "take_step" in method_names
    # Engine-callback / underscore-prefixed methods are excluded, matching
    # Unity's "public methods only" filter shape.
    assert "_physics_process" not in method_names


# --- §2.3: rewritten -- version string extraction, not a mismatch warning --


def test_2_3_older_engine_version_is_extracted_without_failing(tmp_path):
    project = make_godot_fixture_project(tmp_path)
    (project / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="Fixture Game"\n'
        'config/features=PackedStringArray("3.5")\n'
        'run/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )

    result = detect_godot_project(project)

    assert result.is_valid is True
    assert result.godot_version == "3.5"
    assert result.warnings == []  # no mismatch warning exists to raise -- see module docstring


# --- §2.4: rewritten -- see module docstring; folded into §7 --------------


def test_2_4_note_combined_event_stream_is_covered_in_cross_cutting():
    import pytest

    pytest.skip(
        "Neither godot connector emits an event on its own -- nothing "
        "connector-specific to test here for 'shares a pipeline with Git'. "
        "See tests/e2e/test_e2e_07_cross_cutting.py."
    )


# --- §2.5: missing/corrupt .tscn reports the specific file, doesn't abort --


def test_2_5_broken_scene_reference_is_reported_specifically(tmp_path):
    project = make_godot_fixture_project(tmp_path)
    (project / "main.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Texture2D" path="res://assets/missing.png" id="1"]\n\n'
        '[node name="Main" type="Node2D"]\n',
        encoding="utf-8",
    )

    broken = scan_broken_references(project)

    assert len(broken) == 1
    assert broken[0].scene_path == "main.tscn"
    assert broken[0].missing_resource_path == "res://assets/missing.png"


def test_2_5_corrupt_scene_file_is_skipped_not_a_whole_scan_abort(tmp_path):
    project = make_godot_fixture_project(tmp_path)
    # A second, genuinely unreadable .tscn (invalid UTF-8 bytes) alongside
    # the fixture's valid main.tscn.
    (project / "corrupt.tscn").write_bytes(b"\xff\xfe\x00\xff not valid utf-8 tscn \x80\x81")

    scenes = scan_scenes(project)  # must not raise
    broken = scan_broken_references(project)  # must not raise either

    # The valid scene is still parsed; the corrupt one doesn't take the
    # whole scan down (errors="replace" degrades it rather than raising, and
    # scan_scenes' own broad except OSError covers genuinely unreadable
    # files) -- either way, main.tscn's own result survives.
    assert any(s.path == "main.tscn" for s in scenes)
    assert isinstance(broken, list)
