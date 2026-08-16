"""Design Doc Sync use-case (Phase F, section 6, Stretch tier).

The developer uploads or pastes *their own game's* design doc per project —
never the Spiced product spec — and Spiced compares it against the latest
Auto-Generated Dev Docs snapshot (``core.dev_docs``) via the AI provider,
flagging meaningful drift either direction. Framed as "reconcile the doc or
rein in scope," never a verdict — see ``build_design_doc_sync_prompt``.

Opt-in per project (``projects.design_doc_sync_enabled``), per spec.

Import format decision: plain ``.txt``/``.md`` are read directly. ``.docx``
support uses the same lightweight approach the plan calls out as acceptable
— unzip the file and regex-extract ``<w:t>`` text runs, paragraph by
paragraph — rather than pulling in a full docx-parsing dependency. This
loses styling/tables/images, but for a design doc's plain text content
(the only thing the AI comparison needs) that's an acceptable trade documented
here rather than silently expanding scope with a new dependency.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_design_doc_sync_prompt
from spiced.core.dev_docs import DevDocsService
from spiced.storage.design_doc_sync_reports import (
    DesignDocSyncReport,
    DesignDocSyncReportRepository,
)
from spiced.storage.design_doc_uploads import DesignDocUpload, DesignDocUploadRepository
from spiced.storage.dev_docs_snapshots import DevDocsSnapshot
from spiced.storage.projects import Project

SUPPORTED_TEXT_EXTS = {".txt", ".md"}
SUPPORTED_EXTS = SUPPORTED_TEXT_EXTS | {".docx"}

_DOCX_PARAGRAPH_RE = re.compile(r"<w:p[ >].*?</w:p>", flags=re.DOTALL)
_DOCX_RUN_RE = re.compile(r"<w:t[^>]*>(.*?)</w:t>", flags=re.DOTALL)


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class DesignDocSyncNotEnabledError(RuntimeError):
    """Raised when the project hasn't opted into Design Doc Sync."""


class NoDesignDocError(RuntimeError):
    """Raised when the project has no uploaded/pasted design doc text yet."""


class UnsupportedDesignDocFormatError(RuntimeError):
    """Raised when an imported file isn't a supported format."""


def import_design_doc_text(path: str | Path) -> str:
    """Read a design-doc file's plain text.

    Supports ``.txt``/``.md`` directly and a minimal ``.docx`` extraction
    (see module docstring). Raises ``UnsupportedDesignDocFormatError`` for
    anything else — the developer can always paste text directly instead.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in SUPPORTED_TEXT_EXTS:
        return p.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        return _extract_docx_text(p)
    raise UnsupportedDesignDocFormatError(
        f'Unsupported design doc format "{suffix}" — import a .txt, .md, or .docx file, or '
        "paste the text directly."
    )


def _extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    paragraphs = []
    for para_xml in _DOCX_PARAGRAPH_RE.findall(xml):
        runs = _DOCX_RUN_RE.findall(para_xml)
        paragraphs.append("".join(runs))
    return "\n".join(paragraphs)


@dataclass(frozen=True)
class DesignDocSyncResult:
    upload: DesignDocUpload
    snapshot: DevDocsSnapshot
    response_text: str
    provider: str
    report: DesignDocSyncReport


class DesignDocSyncService:
    def __init__(
        self,
        uploads: DesignDocUploadRepository,
        reports: DesignDocSyncReportRepository,
        dev_docs: DevDocsService,
    ) -> None:
        self._uploads = uploads
        self._reports = reports
        self._dev_docs = dev_docs

    def upload_text(
        self, project_id: int, text: str, filename: str | None = None
    ) -> DesignDocUpload:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Design doc text is empty.")
        return self._uploads.create(project_id, cleaned, filename)

    def latest_upload(self, project_id: int) -> DesignDocUpload | None:
        return self._uploads.latest_for_project(project_id)

    def upload_history(self, project_id: int, limit: int = 20) -> list[DesignDocUpload]:
        return self._uploads.list_for_project(project_id, limit=limit)

    def compare(
        self,
        provider: AIProvider,
        project: Project,
        *,
        record_usage=None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> DesignDocSyncResult:
        """Compare the latest uploaded design doc against the latest Dev
        Docs snapshot, generating one first if the project has none yet (per
        spec). Raises ``DesignDocSyncNotEnabledError`` if the project hasn't
        opted in, ``NoDesignDocError`` if nothing has been uploaded/pasted
        yet, and ``ProviderNotReadyError`` if the provider isn't usable.
        """
        if not project.design_doc_sync_enabled:
            raise DesignDocSyncNotEnabledError(
                "Design Doc Sync is off for this project. Turn it on for this project first "
                "(Projects screen)."
            )
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )
        upload = self.latest_upload(project.id)
        if upload is None:
            raise NoDesignDocError(
                "Upload or paste your game's design doc for this project first."
            )

        snapshot = self._dev_docs.latest(project.id)
        if snapshot is None:
            generated = self._dev_docs.generate(provider, project, record_usage=record_usage)
            snapshot = generated.snapshot

        prompt = build_design_doc_sync_prompt(
            design_doc_text=upload.text,
            dev_docs_summary=snapshot.ai_summary or "",
            scan_summary=snapshot.source_summary,
            project_name=project.name,
        )
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
            response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        report = self._reports.create(
            project_id=project.id,
            design_doc_upload_id=upload.id,
            dev_docs_snapshot_id=snapshot.id,
            ai_summary=response.text,
            provider=response.provider,
        )
        return DesignDocSyncResult(
            upload=upload,
            snapshot=snapshot,
            response_text=response.text,
            provider=response.provider,
            report=report,
        )

    def history(self, project_id: int, limit: int = 20) -> list[DesignDocSyncReport]:
        return self._reports.list_for_project(project_id, limit=limit)
