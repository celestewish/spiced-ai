"""Tests for core.dev_docs: scan orchestration + versioned snapshots."""

from __future__ import annotations

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.core.dev_docs import DevDocsService, NoProjectFolderError, ProviderNotReadyError
from spiced.storage.database import Database
from spiced.storage.dev_docs_snapshots import DevDocsSnapshotRepository
from spiced.storage.projects import ProjectRepository

CANNED = "Here's a living summary of your project's scripts.\n\nSystems overview:\n- none"


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available
        self.calls = 0

    def is_available(self):
        return self._available

    def generate(self, prompt):
        self.calls += 1
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


def _project(tmp_path, repo):
    project = repo.create("Moonlit Depths", engine="Unity")
    return repo.set_unity_folder(project.id, str(tmp_path), "unknown")


def _write_script(tmp_path, rel_path: str, content: str) -> None:
    path = tmp_path / "Assets" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _service(db):
    return DevDocsService(DevDocsSnapshotRepository(db))


def test_scan_raises_without_unity_folder():
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = repo.create("No Folder")
    service = _service(db)
    with pytest.raises(NoProjectFolderError):
        service.scan(project)


def test_scan_dispatches_to_godot_scan_for_godot_projects(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = repo.create("A Godot Game", engine="Godot")
    project = repo.set_unity_folder(project.id, str(tmp_path), "valid")
    (tmp_path / "player.gd").write_text(
        "func move(direction):\n\tposition += direction\n", encoding="utf-8"
    )
    service = _service(db)

    result = service.scan(project)

    assert result.file_count == 1
    assert result.classes[0].name == "player"
    assert result.classes[0].methods[0].name == "move"


def test_scan_dispatches_to_unreal_scan_for_unreal_projects(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = repo.create("An Unreal Game", engine="Unreal")
    project = repo.set_unity_folder(project.id, str(tmp_path), "valid")
    header_dir = tmp_path / "Source" / "TPS"
    header_dir.mkdir(parents=True)
    (header_dir / "Battery.h").write_text(
        "class TPS_API Battery\n{\npublic:\n    float GetPercent() const;\n};\n",
        encoding="utf-8",
    )
    service = _service(db)

    result = service.scan(project)

    assert result.file_count == 1
    assert result.classes[0].name == "Battery"
    assert result.classes[0].methods[0].name == "GetPercent"


def test_generate_raises_when_provider_unavailable(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo)
    service = _service(db)
    with pytest.raises(ProviderNotReadyError):
        service.generate(FakeProvider(available=False), project)


def test_generate_saves_a_snapshot_with_the_raw_scan_and_ai_summary(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo)
    _write_script(
        tmp_path,
        "Scripts/PlayerController.cs",
        "public class PlayerController\n{\n    public void Move()\n    {\n    }\n}\n",
    )
    service = _service(db)
    usage = []

    result = service.generate(FakeProvider(), project, record_usage=usage.append)

    assert result.response_text == CANNED
    assert usage == ["fake"]
    assert result.snapshot.class_count == 1
    assert result.snapshot.method_count == 1
    assert result.snapshot.ai_summary == CANNED
    assert service.latest(project.id).id == result.snapshot.id


def test_each_generation_is_a_new_versioned_row(tmp_path):
    """Regenerating (a button click) must never overwrite the previous
    snapshot — Scope-Creep Flagging depends on a real history existing."""
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo)
    class_a = "public class A\n{\n    public void Foo()\n    {\n    }\n}\n"
    _write_script(tmp_path, "Scripts/A.cs", class_a)
    service = _service(db)

    first = service.generate(FakeProvider(), project)

    class_b = "public class B\n{\n    public void Bar()\n    {\n    }\n}\n"
    _write_script(tmp_path, "Scripts/B.cs", class_b)
    second = service.generate(FakeProvider(), project)

    assert first.snapshot.id != second.snapshot.id
    assert second.snapshot.class_count == 2  # A and B both scanned

    history = service.history(project.id)
    assert len(history) == 2
    assert history[0].id == second.snapshot.id  # newest-first
    assert history[1].id == first.snapshot.id
