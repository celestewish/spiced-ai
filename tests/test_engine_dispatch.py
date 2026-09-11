"""core.engine_dispatch.detect_engine(): run all three folder detectors
against a folder and report which one (if any) recognizes it.

Connect-a-Project Setup Simplification spec, Finding 1 fix 1/fix 4. Fixture
shapes mirror the same minimal marker files ``tests/e2e/conftest.py`` builds
for its own Godot/Unreal fixtures (kept local here rather than imported
across test directories, since ``tests/`` has no ``__init__.py`` packages to
import through).
"""

from __future__ import annotations

import json

from spiced.core.engine_dispatch import ENGINE_GODOT, ENGINE_UNITY, ENGINE_UNREAL, detect_engine


def _make_unity_project(root) -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()


def _make_godot_project(root) -> None:
    (root / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="Fixture Game"\n',
        encoding="utf-8",
    )


def _make_unreal_project(root, name: str = "FixtureGame") -> None:
    (root / f"{name}.uproject").write_text(
        json.dumps({"FileVersion": 3, "EngineAssociation": "5.3"}), encoding="utf-8"
    )


def test_detects_a_godot_project(tmp_path):
    _make_godot_project(tmp_path)

    engine, detection = detect_engine(tmp_path)

    assert engine == ENGINE_GODOT
    assert detection.is_valid is True
    assert detection.project_name == "Fixture Game"


def test_detects_an_unreal_project(tmp_path):
    _make_unreal_project(tmp_path)

    engine, detection = detect_engine(tmp_path)

    assert engine == ENGINE_UNREAL
    assert detection.is_valid is True
    assert detection.engine_association == "5.3"


def test_detects_a_unity_project(tmp_path):
    _make_unity_project(tmp_path)

    engine, detection = detect_engine(tmp_path)

    assert engine == ENGINE_UNITY
    assert detection.is_valid is True


def test_unrecognized_folder_falls_back_to_unity_shaped_invalid_result(tmp_path):
    # Empty folder -- none of the three marker files exist.
    engine, detection = detect_engine(tmp_path)

    assert engine == ENGINE_UNITY
    assert detection.is_valid is False
    assert any("Assets" in w for w in detection.warnings)


def test_godot_marker_wins_even_if_the_folder_also_has_unity_shaped_dirs(tmp_path):
    # A folder that happens to have Assets/+ProjectSettings/ *and* a real
    # project.godot (e.g. a migrated project mid-conversion) should still be
    # recognized as Godot -- Godot/Unreal are checked before Unity's pair
    # check, which is also the fallback shape (see detect_engine's docstring).
    _make_unity_project(tmp_path)
    _make_godot_project(tmp_path)

    engine, detection = detect_engine(tmp_path)

    assert engine == ENGINE_GODOT
    assert detection.is_valid is True


def test_does_not_raise_on_a_nonexistent_folder(tmp_path):
    missing = tmp_path / "does-not-exist"

    engine, detection = detect_engine(missing)

    assert engine == ENGINE_UNITY
    assert detection.is_valid is False
