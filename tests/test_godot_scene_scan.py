"""Tests for connectors.godot_scene_scan.

The sample text below is a trimmed, faithful reproduction of a real Godot 4
``.tscn`` file (fetched from ``godotengine/godot-demo-projects``, ``2d/
dodge_the_creeps/main.tscn``, during development to verify field names/
layout -- see the module's docstring): an ``ext_resource`` per dependency,
a ``sub_resource`` with a multi-line body, an instanced-subscene node with
no ``type=`` attribute, and ``[connection]`` signal wiring.
"""

from __future__ import annotations

from spiced.connectors.godot_scene_scan import parse_scene_text, scan_broken_references

MAIN_TSCN_TEXT = """[gd_scene format=3 uid="uid://bggkaprn62fwm"]

[ext_resource type="Script" uid="uid://c4wt6ace7hycd" path="res://main.gd" id="1_0r6n5"]
[ext_resource type="PackedScene" uid="uid://cao351pllxqpa" path="res://mob.tscn" id="2_50pww"]
[ext_resource type="PackedScene" uid="uid://bwhlkliwp13p4" path="res://player.tscn" id="3_veqnc"]

[sub_resource type="Curve2D" id="1"]
_data = {
"points": PackedVector2Array(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 480, 0)
}
point_count = 5

[node name="Main" type="Node" unique_id=1975992027]
script = ExtResource("1_0r6n5")
mob_scene = ExtResource("2_50pww")

[node name="Player" parent="." unique_id=927660131 instance=ExtResource("3_veqnc")]

[node name="MobTimer" type="Timer" parent="." unique_id=228987391]
wait_time = 0.5

[connection signal="hit" from="Player" to="." method="game_over"]
[connection signal="timeout" from="MobTimer" to="." method="_on_MobTimer_timeout"]
"""


def test_parse_scene_text_extracts_ext_resources():
    scene = parse_scene_text(MAIN_TSCN_TEXT, "main.tscn")

    paths = {r.path for r in scene.ext_resources}
    assert paths == {"res://main.gd", "res://mob.tscn", "res://player.tscn"}


def test_parse_scene_text_extracts_node_tree_including_instanced_subscene():
    scene = parse_scene_text(MAIN_TSCN_TEXT, "main.tscn")

    by_name = {n.name: n for n in scene.nodes}
    assert by_name["Main"].type == "Node"
    assert by_name["Main"].parent is None
    assert by_name["Player"].type is None  # instanced sub-scene: no type=
    assert by_name["Player"].parent == "."
    assert by_name["MobTimer"].type == "Timer"


def test_parse_scene_text_ignores_sub_resource_body_lines():
    """The multi-line _data = {...} body under [sub_resource] must not be
    mistaken for a header -- confirms the parser only reads bracket-header
    lines, never body content."""
    scene = parse_scene_text(MAIN_TSCN_TEXT, "main.tscn")

    assert len(scene.nodes) == 3  # not inflated by the sub_resource body


def test_parse_scene_text_extracts_connections():
    scene = parse_scene_text(MAIN_TSCN_TEXT, "main.tscn")

    assert len(scene.connections) == 2
    hit_connection = next(c for c in scene.connections if c.signal == "hit")
    assert hit_connection.from_node == "Player"
    assert hit_connection.to_node == "."
    assert hit_connection.method == "game_over"


def test_scan_broken_references_flags_missing_file(tmp_path):
    (tmp_path / "main.tscn").write_text(MAIN_TSCN_TEXT, encoding="utf-8")
    (tmp_path / "main.gd").write_text("extends Node\n", encoding="utf-8")
    (tmp_path / "mob.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    # player.tscn deliberately not created -- a broken reference.

    broken = scan_broken_references(tmp_path)

    assert len(broken) == 1
    assert broken[0].scene_path == "main.tscn"
    assert broken[0].missing_resource_path == "res://player.tscn"


def test_scan_broken_references_empty_when_all_files_present(tmp_path):
    (tmp_path / "main.tscn").write_text(MAIN_TSCN_TEXT, encoding="utf-8")
    (tmp_path / "main.gd").write_text("extends Node\n", encoding="utf-8")
    (tmp_path / "mob.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    (tmp_path / "player.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")

    assert scan_broken_references(tmp_path) == []
