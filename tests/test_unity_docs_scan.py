"""Tests for connectors.unity_docs_scan: the read-only .cs signature scanner
backing Auto-Generated Dev Docs.

Builds a small crafted C# fixture under tmp_path — no real Unity project or
compiler is ever needed, since extraction is a regex scan, not a real parser.
"""

from __future__ import annotations

from spiced.connectors.unity_docs_scan import DevDocsScanResult, scan_scripts

_FIXTURE_CS = """\
using UnityEngine;

namespace Game.Player
{
    /// <summary>
    /// Handles player movement and jumping.
    /// </summary>
    public class PlayerController : MonoBehaviour
    {
        // Moves the player by the given delta.
        public void Move(Vector3 delta)
        {
            transform.position += delta;
        }

        /// <summary>
        /// Makes the player jump.
        /// </summary>
        public void Jump()
        {
        }

        public float GetSpeed()
        {
            return 5f;
        }

        private void InternalHelper()
        {
        }
    }

    public class EnemySpawner
    {
        public void Spawn()
        {
        }
    }
}
"""


def _write_script(tmp_path, rel_path: str, content: str) -> None:
    path = tmp_path / "Assets" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_scripts_returns_empty_result_without_assets_folder(tmp_path):
    result = scan_scripts(tmp_path)
    assert result == DevDocsScanResult()
    assert result.class_count == 0
    assert result.method_count == 0


def test_scan_scripts_extracts_classes_and_public_methods(tmp_path):
    _write_script(tmp_path, "Scripts/PlayerController.cs", _FIXTURE_CS)

    result = scan_scripts(tmp_path)

    assert result.file_count == 1
    assert result.class_count == 2
    class_names = {c.name for c in result.classes}
    assert class_names == {"PlayerController", "EnemySpawner"}

    player = next(c for c in result.classes if c.name == "PlayerController")
    assert player.file == "Assets/Scripts/PlayerController.cs"
    assert player.doc_comment is not None
    assert "Handles player movement and jumping." in player.doc_comment

    method_names = [m.name for m in player.methods]
    # Move, Jump, GetSpeed are public; InternalHelper is private and skipped.
    assert method_names == ["Move", "Jump", "GetSpeed"]

    move = next(m for m in player.methods if m.name == "Move")
    assert move.doc_comment == "Moves the player by the given delta."
    assert "public void Move(Vector3 delta)" in move.signature

    jump = next(m for m in player.methods if m.name == "Jump")
    assert jump.doc_comment is not None
    assert "Makes the player jump." in jump.doc_comment

    get_speed = next(m for m in player.methods if m.name == "GetSpeed")
    assert get_speed.doc_comment is None

    spawner = next(c for c in result.classes if c.name == "EnemySpawner")
    assert spawner.doc_comment is None
    assert [m.name for m in spawner.methods] == ["Spawn"]


def test_scan_scripts_skips_non_cs_files(tmp_path):
    _write_script(tmp_path, "Scripts/Notes.txt", "public class NotReallyCode {}")
    result = scan_scripts(tmp_path)
    assert result.file_count == 0
    assert result.class_count == 0


def test_as_summary_dict_round_trips_class_and_method_counts(tmp_path):
    _write_script(tmp_path, "Scripts/PlayerController.cs", _FIXTURE_CS)
    result = scan_scripts(tmp_path)
    summary = result.as_summary_dict()
    assert summary["file_count"] == 1
    assert summary["class_count"] == 2
    assert summary["method_count"] == 4  # Move, Jump, GetSpeed, Spawn
    names = {c["name"] for c in summary["classes"]}
    assert names == {"PlayerController", "EnemySpawner"}
