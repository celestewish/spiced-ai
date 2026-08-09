"""Tests for storage.visual_regression_key_scenes.VisualRegressionKeySceneRepository
(Implementation Bible, Feature 2)."""

from __future__ import annotations

import pytest

from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.visual_regression_key_scenes import VisualRegressionKeySceneRepository


def _setup():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    key_scenes = VisualRegressionKeySceneRepository(db)
    project = projects.create("Moonlit Depths")
    return key_scenes, project


def test_add_and_get():
    key_scenes, project = _setup()
    record = key_scenes.add(
        project.id, "Assets/Scenes/Main.unity", "Main Hall", "Cap_MainHall"
    )
    assert record.id is not None
    fetched = key_scenes.get(record.id)
    assert fetched == record


def test_add_rejects_blank_fields():
    key_scenes, project = _setup()
    with pytest.raises(ValueError):
        key_scenes.add(project.id, "", "Main Hall", "Cap_MainHall")
    with pytest.raises(ValueError):
        key_scenes.add(project.id, "Assets/Scenes/Main.unity", "  ", "Cap_MainHall")
    with pytest.raises(ValueError):
        key_scenes.add(project.id, "Assets/Scenes/Main.unity", "Main Hall", "")


def test_get_missing_raises_key_error():
    key_scenes, _project = _setup()
    with pytest.raises(KeyError):
        key_scenes.get(999)


def test_list_for_project_ordered_and_scoped():
    key_scenes, project = _setup()
    key_scenes.add(project.id, "Assets/Scenes/A.unity", "A", "CapA")
    key_scenes.add(project.id, "Assets/Scenes/B.unity", "B", "CapB")

    records = key_scenes.list_for_project(project.id)

    assert [r.label for r in records] == ["A", "B"]


def test_list_for_project_empty():
    key_scenes, project = _setup()
    assert key_scenes.list_for_project(project.id) == []


def test_delete():
    key_scenes, project = _setup()
    record = key_scenes.add(project.id, "Assets/Scenes/A.unity", "A", "CapA")

    key_scenes.delete(record.id)

    assert key_scenes.list_for_project(project.id) == []
    with pytest.raises(KeyError):
        key_scenes.get(record.id)
