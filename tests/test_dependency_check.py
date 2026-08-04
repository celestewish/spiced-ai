"""Tests for core.dependency_check: manifest parsing + orchestration.

Registry lookups are mocked (via connectors.unity_package_registry's own
mocked httpx client covered in test_unity_package_registry.py) — here we
mock at the connectors.unity_package_registry.fetch_package_info boundary so
these tests never make a real network request.
"""

from __future__ import annotations

import json

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.connectors.unity_package_registry import PackageRegistryInfo
from spiced.core.dependency_check import (
    DependencyCheckService,
    NoManifestError,
    NoUnityFolderError,
    ProviderNotReadyError,
    check_dependencies,
)
from spiced.storage.database import Database
from spiced.storage.dependency_check_reports import DependencyCheckReportRepository
from spiced.storage.projects import ProjectRepository

CANNED = "Here's the dependency check.\n\nOutdated packages:\n- None found."


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


def _project(tmp_path, repo):
    project = repo.create("Moonlit Depths", engine="Unity")
    return repo.set_unity_folder(project.id, str(tmp_path), "unknown")


def _write_manifest(tmp_path, dependencies: dict) -> None:
    packages_dir = tmp_path / "Packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    (packages_dir / "manifest.json").write_text(
        json.dumps({"dependencies": dependencies}), encoding="utf-8"
    )


def test_check_dependencies_raises_without_unity_folder():
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = repo.create("No Folder")
    with pytest.raises(NoUnityFolderError):
        check_dependencies(project)


def test_check_dependencies_raises_without_manifest(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo)
    with pytest.raises(NoManifestError):
        check_dependencies(project)


def test_check_dependencies_flags_outdated_package(tmp_path, monkeypatch):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo)
    _write_manifest(tmp_path, {"com.unity.timeline": "1.0.0"})

    def fake_fetch(name, base_url, timeout_s):
        return PackageRegistryInfo(name=name, latest_version="1.8.12", found=True)

    monkeypatch.setattr(
        "spiced.connectors.unity_package_registry.fetch_package_info", fake_fetch
    )

    findings = check_dependencies(project)
    assert len(findings.results) == 1
    assert findings.results[0].outdated is True
    assert findings.outdated_count == 1
    assert findings.unchecked_count == 0


def test_check_dependencies_handles_registry_failure_gracefully(tmp_path, monkeypatch):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo)
    _write_manifest(tmp_path, {"com.unity.timeline": "1.0.0"})

    def fake_fetch(name, base_url, timeout_s):
        return PackageRegistryInfo(name=name, latest_version=None, found=False, error="offline")

    monkeypatch.setattr(
        "spiced.connectors.unity_package_registry.fetch_package_info", fake_fetch
    )

    findings = check_dependencies(project)
    assert findings.unchecked_count == 1
    assert findings.outdated_count == 0


def test_check_dependencies_skips_local_dependency(tmp_path, monkeypatch):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo)
    _write_manifest(tmp_path, {"com.mycompany.thing": "file:../ThingPackage"})

    calls = []

    def fake_fetch(name, base_url, timeout_s):
        calls.append(name)
        return PackageRegistryInfo(name=name, latest_version="1.0.0", found=True)

    monkeypatch.setattr(
        "spiced.connectors.unity_package_registry.fetch_package_info", fake_fetch
    )

    findings = check_dependencies(project)
    assert calls == []
    assert findings.results[0].checked is False


# --- DependencyCheckService (AI layer) ---------------------------------------


def _service(db):
    return DependencyCheckService(DependencyCheckReportRepository(db))


def test_analyze_raises_when_provider_unavailable(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo)
    _write_manifest(tmp_path, {})
    service = _service(db)
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), project)


def test_analyze_saves_report(tmp_path, monkeypatch):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo)
    _write_manifest(tmp_path, {"com.unity.timeline": "1.0.0"})

    def fake_fetch(name, base_url, timeout_s):
        return PackageRegistryInfo(name=name, latest_version="1.0.0", found=True)

    monkeypatch.setattr(
        "spiced.connectors.unity_package_registry.fetch_package_info", fake_fetch
    )

    service = _service(db)
    usage = []
    review = service.analyze(FakeProvider(), project, record_usage=usage.append)

    assert review.response_text == CANNED
    assert review.report is not None
    assert usage == ["fake"]
    assert service.history(project.id)[0].id == review.report.id
