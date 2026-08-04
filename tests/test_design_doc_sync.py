"""Tests for core.design_doc_sync: opt-in gating, drift detection (mocked
AI), and the .txt/.md/.docx import helper."""

from __future__ import annotations

import re
import zipfile

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.core.design_doc_sync import (
    DesignDocSyncNotEnabledError,
    DesignDocSyncService,
    NoDesignDocError,
    ProviderNotReadyError,
    UnsupportedDesignDocFormatError,
    import_design_doc_text,
)
from spiced.core.dev_docs import DevDocsService
from spiced.storage.database import Database
from spiced.storage.design_doc_sync_reports import DesignDocSyncReportRepository
from spiced.storage.design_doc_uploads import DesignDocUploadRepository
from spiced.storage.dev_docs_snapshots import DevDocsSnapshotRepository
from spiced.storage.projects import ProjectRepository

CANNED = "Here's the design-doc drift check.\n\nImplemented but not in the design doc:\n- None."


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


def _project(tmp_path, repo, *, design_doc_sync_enabled=False):
    project = repo.create("Moonlit Depths", engine="Unity")
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")
    if design_doc_sync_enabled:
        project = repo.set_design_doc_sync_settings(project.id, True)
    return project


def _write_script(tmp_path, rel_path: str, content: str) -> None:
    path = tmp_path / "Assets" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _service(db):
    dev_docs = DevDocsService(DevDocsSnapshotRepository(db))
    return (
        DesignDocSyncService(
            DesignDocUploadRepository(db),
            DesignDocSyncReportRepository(db),
            dev_docs,
        ),
        dev_docs,
    )


# --- Opt-in gating -----------------------------------------------------------


def test_compare_raises_when_project_has_not_opted_in(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo, design_doc_sync_enabled=False)
    service, _ = _service(db)

    with pytest.raises(DesignDocSyncNotEnabledError):
        service.compare(FakeProvider(), project)


def test_compare_raises_without_a_design_doc_even_when_enabled(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo, design_doc_sync_enabled=True)
    service, _ = _service(db)

    with pytest.raises(NoDesignDocError):
        service.compare(FakeProvider(), project)


def test_compare_raises_when_provider_unavailable(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo, design_doc_sync_enabled=True)
    service, _ = _service(db)
    service.upload_text(project.id, "A simple design doc.")

    with pytest.raises(ProviderNotReadyError):
        service.compare(FakeProvider(available=False), project)


# --- Drift detection (mocked AI) ---------------------------------------------


def test_compare_generates_a_dev_docs_snapshot_if_none_exists_yet(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo, design_doc_sync_enabled=True)
    _write_script(
        tmp_path, "Scripts/A.cs", "public class A\n{\n    public void Foo()\n    {\n    }\n}\n"
    )
    service, dev_docs = _service(db)
    service.upload_text(project.id, "A simple design doc.")

    assert dev_docs.latest(project.id) is None  # nothing generated yet

    result = service.compare(FakeProvider(), project)

    assert result.response_text == CANNED
    assert dev_docs.latest(project.id) is not None
    assert result.snapshot.id == dev_docs.latest(project.id).id
    assert result.report.ai_summary == CANNED
    assert service.history(project.id)[0].id == result.report.id


def test_compare_reuses_the_latest_existing_snapshot(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo, design_doc_sync_enabled=True)
    service, dev_docs = _service(db)
    service.upload_text(project.id, "A simple design doc.")
    existing = dev_docs.generate(FakeProvider(), project)

    provider = FakeProvider()
    result = service.compare(provider, project)

    assert result.snapshot.id == existing.snapshot.id
    assert provider.calls == 1  # only the comparison call, no extra generation


def test_upload_text_rejects_empty_text(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo, design_doc_sync_enabled=True)
    service, _ = _service(db)
    with pytest.raises(ValueError):
        service.upload_text(project.id, "   ")


def test_upload_history_returns_uploads_newest_first(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = _project(tmp_path, repo, design_doc_sync_enabled=True)
    service, _ = _service(db)
    first = service.upload_text(project.id, "Draft one.")
    second = service.upload_text(project.id, "Draft two.")
    assert service.latest_upload(project.id).id == second.id
    history = service.upload_history(project.id)
    assert [u.id for u in history] == [second.id, first.id]


# --- Import helper (.txt/.md/.docx) ------------------------------------------


def test_import_txt_file_reads_plain_text(tmp_path):
    path = tmp_path / "design.txt"
    path.write_text("The player collects gems.", encoding="utf-8")
    assert import_design_doc_text(path) == "The player collects gems."


def test_import_md_file_reads_plain_text(tmp_path):
    path = tmp_path / "design.md"
    path.write_text("# Design\n\nThe player collects gems.", encoding="utf-8")
    assert "The player collects gems." in import_design_doc_text(path)


def test_import_unsupported_extension_raises():
    with pytest.raises(UnsupportedDesignDocFormatError):
        import_design_doc_text("design.pdf")


def _write_minimal_docx(path, paragraphs: list[str]) -> None:
    """Build a minimal, valid .docx (a zip with word/document.xml) so the
    import helper's unzip + <w:t> regex extraction has something real to
    read — mirrors the structure real Word output has, just hand-written."""
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://example.com/w">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


def test_import_docx_extracts_paragraph_text(tmp_path):
    path = tmp_path / "design.docx"
    _write_minimal_docx(path, ["Overview", "The player collects gems and fights enemies."])
    text = import_design_doc_text(path)
    assert "Overview" in text
    assert "The player collects gems and fights enemies." in text
    # Paragraphs should be kept distinguishable rather than run together.
    assert re.search(r"Overview\n.*collects gems", text, flags=re.DOTALL)
