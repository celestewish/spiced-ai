import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.connectors.unity_scan import OVERSIZED_TEXTURE_BYTES
from spiced.core.asset_scan import AssetScanService, NoProjectFolderError, ProviderNotReadyError
from spiced.storage.asset_scan_reports import AssetScanReportRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

CANNED = "Here's the asset sweep.\n\nOversized or uncompressed files:\n- None found."


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


def _service():
    db = Database(":memory:")
    projects_repo = ProjectRepository(db)
    project = projects_repo.create("Moonlit Depths", engine="Unity")
    return AssetScanService(AssetScanReportRepository(db)), project, projects_repo


def test_scan_raises_without_a_project_folder():
    service, project, _repo = _service()
    with pytest.raises(NoProjectFolderError):
        service.scan(project)


def test_scan_finds_oversized_texture(tmp_path):
    service, project, repo = _service()
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")
    big_png = tmp_path / "Assets" / "Textures" / "bg.png"
    big_png.parent.mkdir(parents=True)
    big_png.write_bytes(b"\0" * (OVERSIZED_TEXTURE_BYTES + 1))

    findings = service.scan(project)
    assert len(findings.oversized) == 1
    assert findings.oversized[0].kind == "texture"
    assert "Resources.Load" in findings.orphan_caveat


def test_analyze_raises_when_provider_unavailable(tmp_path):
    service, project, repo = _service()
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), project)


def test_analyze_saves_report_with_findings_and_summary(tmp_path):
    service, project, repo = _service()
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")

    usage = []
    review = service.analyze(FakeProvider(), project, record_usage=usage.append)

    assert review.response_text == CANNED
    assert review.report is not None
    assert review.report.findings == {
        "oversized": [],
        "orphaned_assets": [],
        "broken_scene_references": [],
    }
    assert usage == ["fake"]
    assert service.history(project.id)[0].id == review.report.id


def test_as_summary_dict_round_trips_through_storage(tmp_path):
    service, project, repo = _service()
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")
    orphan = tmp_path / "Assets" / "Prefabs" / "Unused.prefab"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"x")
    (orphan.parent / "Unused.prefab.meta").write_text("guid: " + "5" * 32, encoding="utf-8")

    review = service.analyze(FakeProvider(), project)
    assert "Assets/Prefabs/Unused.prefab" in review.report.findings["orphaned_assets"]


def _service_for_engine(engine: str):
    db = Database(":memory:")
    projects_repo = ProjectRepository(db)
    project = projects_repo.create("Fixture Game", engine=engine)
    return AssetScanService(AssetScanReportRepository(db)), project, projects_repo


# --- Engine dispatch: Godot ---------------------------------------------


def test_scan_dispatches_to_godot_scan_for_godot_projects(tmp_path):
    service, project, repo = _service_for_engine("Godot")
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")

    big_png = tmp_path / "art" / "bg.png"
    big_png.parent.mkdir(parents=True)
    big_png.write_bytes(b"\0" * (4 * 1024 * 1024 + 1))  # godot_scan's texture threshold

    findings = service.scan(project)

    assert len(findings.oversized) == 1
    assert findings.oversized[0].kind == "texture"
    assert findings.oversized[0].reason  # a real, non-empty reason -- Godot's own
    assert findings.orphaned_assets == []  # no orphan-scan concept for Godot
    assert findings.broken_scene_references == []


def test_scan_reports_godot_broken_scene_references(tmp_path):
    service, project, repo = _service_for_engine("Godot")
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")

    (tmp_path / "main.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Texture2D" path="res://missing.png" id="1"]\n\n'
        '[node name="Main" type="Node2D"]\n',
        encoding="utf-8",
    )

    findings = service.scan(project)

    assert findings.broken_scene_references == ["main.tscn -> res://missing.png"]


# --- Engine dispatch: Unreal ---------------------------------------------


def test_scan_dispatches_to_unreal_scan_and_synthesizes_a_reason(tmp_path):
    service, project, repo = _service_for_engine("Unreal")
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")

    big_uasset = tmp_path / "Content" / "Textures" / "Huge.uasset"
    big_uasset.parent.mkdir(parents=True)
    with open(big_uasset, "wb") as f:
        f.seek(20 * 1024 * 1024)  # unreal_scan's .uasset threshold
        f.write(b"\0")

    findings = service.scan(project)

    assert len(findings.oversized) == 1
    assert findings.oversized[0].kind == "uasset"
    # OversizedBinaryAssetFinding has no reason field of its own -- confirms
    # AssetScanService synthesizes one rather than leaving it blank/crashing.
    assert findings.oversized[0].reason
    assert findings.broken_scene_references == []  # no scene-reference concept for Unreal
