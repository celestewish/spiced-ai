"""Tests for storage.visual_regression_captures.VisualRegressionCaptureRepository
(Implementation Bible, Feature 2)."""

from __future__ import annotations

import pytest

from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.visual_regression_captures import VisualRegressionCaptureRepository


def _setup():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    captures = VisualRegressionCaptureRepository(db)
    project = projects.create("Moonlit Depths")
    return captures, project


def test_create_and_get():
    captures, project = _setup()
    record = captures.create(project.id, "C:\\proj\\SpicedVisualRegression\\run1")
    assert record.id is not None
    assert captures.get(record.id) == record


def test_get_missing_raises_key_error():
    captures, _project = _setup()
    with pytest.raises(KeyError):
        captures.get(999)


def test_latest_for_project_returns_none_when_empty():
    captures, project = _setup()
    assert captures.latest_for_project(project.id) is None


def test_latest_for_project_returns_most_recent():
    captures, project = _setup()
    captures.create(project.id, "run1")
    second = captures.create(project.id, "run2")

    latest = captures.latest_for_project(project.id)

    assert latest.id == second.id
    assert latest.screenshots_dir == "run2"


def test_list_for_project_scoped_and_ordered():
    captures, project = _setup()
    captures.create(project.id, "run1")
    captures.create(project.id, "run2")

    records = captures.list_for_project(project.id)

    assert [r.screenshots_dir for r in records] == ["run2", "run1"]
