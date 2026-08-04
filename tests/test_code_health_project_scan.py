"""Tests for the Naming Consistency + Dead Reference Detection extension of
CodeHealthService (Phase D) — deterministic project-wide scans folded into
the existing Code Health Dashboard, distinct from its one-pasted-file metrics.
"""

from __future__ import annotations

import pytest

from spiced.core.code_health import CodeHealthService, NoUnityFolderError
from spiced.storage.code_health_reports import CodeHealthReportRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _service():
    db = Database(":memory:")
    projects_repo = ProjectRepository(db)
    project = projects_repo.create("Moonlit Depths", engine="Unity")
    return CodeHealthService(CodeHealthReportRepository(db)), project, projects_repo


def test_scan_naming_convention_raises_without_a_project_folder():
    service, project, _repo = _service()
    with pytest.raises(NoUnityFolderError):
        service.scan_naming_convention(project)


def test_scan_dead_references_raises_without_a_project_folder():
    service, project, _repo = _service()
    with pytest.raises(NoUnityFolderError):
        service.scan_dead_references(project)


def test_scan_naming_convention_delegates_to_the_project_folder(tmp_path):
    service, project, repo = _service()
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")
    for name in ["player_controller.cs", "enemy_spawner.cs", "OutlierName.cs"]:
        path = tmp_path / "Assets" / "Scripts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    result = service.scan_naming_convention(project)
    assert result.dominant_convention == "snake_case"
    assert "Assets/Scripts/OutlierName.cs" in result.outliers


def test_scan_dead_references_delegates_to_the_project_folder(tmp_path):
    service, project, repo = _service()
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")
    scene = tmp_path / "Assets" / "Scenes" / "Main.unity"
    scene.parent.mkdir(parents=True, exist_ok=True)
    # High-entropy guid so it isn't mistaken for a Unity built-in resource.
    missing_guid = "deadbeefdeadbeefdeadbeefdeadbeef"
    scene.write_text(f"m_Script: {{fileID: 1, guid: {missing_guid}, type: 3}}\n")
    (scene.parent / "Main.unity.meta").write_text("guid: " + "b" * 32, encoding="utf-8")

    result = service.scan_dead_references(project)
    assert len(result.broken_references) == 1
    assert result.broken_references[0].missing_guid == missing_guid
