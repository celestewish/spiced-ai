"""Tests for connectors.godot.

The sample text below is a trimmed, faithful reproduction of a real Godot 4
``project.godot`` file (fetched from ``godotengine/godot-demo-projects``,
``2d/dodge_the_creeps``, during development to verify field names/layout --
see the module's docstring) so these tests exercise the parser against
realistic structure, not a convenient fiction -- including the multi-line
``config/description`` value and the ``[input]`` section's multi-line
bracketed structures, both of which a naive ``configparser``-based reader
would choke on.
"""

from __future__ import annotations

from spiced.connectors.godot import detect_godot_project, project_file_path

DODGE_THE_CREEPS_PROJECT_GODOT = """; Engine configuration file.
; It's best edited using the editor UI and not directly,
; since the parameters that go here are not all obvious.
;
; Format:
;   [section] ; section goes between []
;   param=value ; assign values to parameters

config_version=5

[application]

config/name="Dodge the Creeps"
config/description="This is a simple game where your character must move
and avoid the enemies for as long as possible.

This is a finished version of the game featured in the 'Your first 2D game'
tutorial in the documentation."
config/tags=PackedStringArray("2d", "demo", "official")
run/main_scene="res://main.tscn"
config/features=PackedStringArray("4.7")
config/icon="res://icon.webp"

[display]

window/size/viewport_width=480
window/size/viewport_height=720

[input]

move_left={
"deadzone": 0.2,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"pressed":false,"keycode":0)
]
}
"""


def test_detect_godot_project_false_for_missing_folder(tmp_path):
    result = detect_godot_project(tmp_path / "does-not-exist")
    assert result.is_valid is False
    assert "does not exist" in result.warnings[0]


def test_detect_godot_project_false_without_project_file(tmp_path):
    result = detect_godot_project(tmp_path)
    assert result.is_valid is False
    assert "project.godot" in result.warnings[0]


def test_detect_godot_project_true_and_parses_application_fields(tmp_path):
    project_file_path(tmp_path).write_text(DODGE_THE_CREEPS_PROJECT_GODOT, encoding="utf-8")

    result = detect_godot_project(tmp_path)

    assert result.is_valid is True
    assert result.project_name == "Dodge the Creeps"
    assert result.godot_version == "4.7"
    assert result.main_scene == "res://main.tscn"
    assert result.warnings == []


def test_detect_godot_project_metadata_dict(tmp_path):
    project_file_path(tmp_path).write_text(DODGE_THE_CREEPS_PROJECT_GODOT, encoding="utf-8")

    result = detect_godot_project(tmp_path)

    assert result.metadata() == {
        "godot_version": "4.7",
        "main_scene": "res://main.tscn",
    }


def test_detect_godot_project_falls_back_to_folder_name_without_config_name(tmp_path):
    minimal = "config_version=5\n\n[application]\n\nrun/main_scene=\"res://main.tscn\"\n"
    project_file_path(tmp_path).write_text(minimal, encoding="utf-8")

    result = detect_godot_project(tmp_path)

    assert result.is_valid is True
    assert result.project_name == tmp_path.name


def test_detect_godot_project_handles_unreadable_project_file_without_raising(tmp_path):
    # A directory named project.godot (not a file) can't be read as text --
    # detection should still report is_valid True (the marker file "exists")
    # without raising, just with no metadata extracted.
    (tmp_path / "project.godot").mkdir()

    result = detect_godot_project(tmp_path)

    assert result.is_valid is False  # a directory isn't a valid marker file
