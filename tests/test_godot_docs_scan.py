"""Tests for connectors.godot_docs_scan.

``PLAYER_GD_TEXT`` is a trimmed, faithful reproduction of a real GDScript
file (fetched from ``godotengine/godot-demo-projects``, ``2d/dodge_the_
creeps/player.gd``, during development to verify layout conventions -- see
the module's docstring): no ``class_name`` line, tab-indented bodies,
underscore-prefixed engine callbacks, and a real ``@export`` line with a
trailing inline comment.
"""

from __future__ import annotations

from spiced.connectors.godot_docs_scan import scan_scripts

PLAYER_GD_TEXT = """extends Area2D

signal hit

@export var speed = 400 # How fast the player will move (pixels/sec).
var screen_size # Size of the game window.

func _ready():
\tscreen_size = get_viewport_rect().size
\thide()


func start(pos):
\tposition = pos
\trotation = 0
\tshow()


func _on_body_entered(_body):
\thide() # Player disappears after being hit.
\thit.emit()
"""

DOC_COMMENTED_GD_TEXT = """## Controls the player's movement and health.
class_name Player
extends CharacterBody2D

## Speed in pixels per second.
func move(direction):
\tposition += direction
"""


def _write_gd(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_scan_scripts_uses_file_stem_when_no_class_name(tmp_path):
    _write_gd(tmp_path, "player.gd", PLAYER_GD_TEXT)

    result = scan_scripts(tmp_path)

    assert result.file_count == 1
    assert result.class_count == 1
    assert result.classes[0].name == "player"
    assert result.classes[0].file == "player.gd"


def test_scan_scripts_only_extracts_public_non_underscore_methods(tmp_path):
    _write_gd(tmp_path, "player.gd", PLAYER_GD_TEXT)

    result = scan_scripts(tmp_path)

    method_names = {m.name for m in result.classes[0].methods}
    assert method_names == {"start"}  # _ready and _on_body_entered are excluded


def test_scan_scripts_uses_class_name_when_present(tmp_path):
    _write_gd(tmp_path, "player_char.gd", DOC_COMMENTED_GD_TEXT)

    result = scan_scripts(tmp_path)

    assert result.classes[0].name == "Player"


def test_scan_scripts_captures_class_and_method_doc_comments(tmp_path):
    _write_gd(tmp_path, "player_char.gd", DOC_COMMENTED_GD_TEXT)

    result = scan_scripts(tmp_path)
    cls = result.classes[0]

    assert cls.doc_comment == "Controls the player's movement and health."
    assert cls.methods[0].doc_comment == "Speed in pixels per second."


def test_scan_scripts_ignores_non_gd_files(tmp_path):
    (tmp_path / "notes.txt").write_text("not a script", encoding="utf-8")

    result = scan_scripts(tmp_path)

    assert result.file_count == 0
    assert result.classes == []


def test_scan_scripts_empty_for_missing_folder(tmp_path):
    result = scan_scripts(tmp_path / "nope")
    assert result.file_count == 0
    assert result.classes == []


def test_scan_scripts_counts_across_multiple_files(tmp_path):
    _write_gd(tmp_path, "player.gd", PLAYER_GD_TEXT)
    _write_gd(tmp_path, "player_char.gd", DOC_COMMENTED_GD_TEXT)

    result = scan_scripts(tmp_path)

    assert result.file_count == 2
    assert result.class_count == 2
    assert result.method_count == 2  # "start" + "move"
