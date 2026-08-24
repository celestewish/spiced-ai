"""Auto-Generated Dev Docs use-case (Phase F, section 6, Phase 2 tier).

Scans a project's own scripts for class/method signatures and any doc
comments immediately preceding them, then asks the AI provider to turn that
into a living, plain-language summary per system/file. Each generation is a
new versioned row in ``dev_docs_snapshots`` — regenerated only when the
developer clicks the button, never a background file-watcher (a deliberate,
plan-confirmed scope decision). The version history this builds is what
Scope-Creep Flagging (``core.scope_creep``) and Design Doc Sync
(``core.design_doc_sync``) both build on.

Engine dispatch (Market-Viability Roadmap, Phases 2-3): ``.cs``/Unity
scripts are scanned via ``connectors.unity_docs_scan`` (regex-based, not a
real C# parser, which the plan calls sufficient here); ``.gd``/Godot
scripts via ``connectors.godot_docs_scan`` (GDScript's own doc-comment
convention needs its own regex, not a port of the C# one); ``.h``/``.hpp``
Unreal headers via ``connectors.unreal_docs_scan`` (Unreal's Blueprint
visual scripts are binary ``.uasset`` files and cannot be scanned this way
at all — see that module's docstring for the honest statement of that
limit). All three return the same ``DevDocsScanResult``/``ScannedClass``/
``ScannedMethod`` shape, so everything below this point (the AI prompt, the
snapshot storage) is genuinely engine-agnostic and needed no changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_dev_docs_prompt
from spiced.connectors import godot_docs_scan, unity_docs_scan, unreal_docs_scan
from spiced.connectors.unity_docs_scan import DevDocsScanResult
from spiced.storage.dev_docs_snapshots import DevDocsSnapshot, DevDocsSnapshotRepository
from spiced.storage.projects import Project


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class NoProjectFolderError(RuntimeError):
    """Raised when the project has no connected folder to scan."""


@dataclass(frozen=True)
class DevDocsResult:
    scan: DevDocsScanResult
    response_text: str
    provider: str
    snapshot: DevDocsSnapshot


class DevDocsService:
    def __init__(self, snapshots: DevDocsSnapshotRepository) -> None:
        self._snapshots = snapshots

    def scan(self, project: Project) -> DevDocsScanResult:
        """Local, deterministic, no AI call — free to run any time."""
        if not project.path:
            raise NoProjectFolderError(
                f"Connect a {project.engine} folder for this project first (Projects screen)."
            )
        if project.engine == "Godot":
            return godot_docs_scan.scan_scripts(project.path)
        if project.engine == "Unreal":
            return unreal_docs_scan.scan_headers(project.path)
        return unity_docs_scan.scan_scripts(project.path)

    def generate(
        self,
        provider: AIProvider,
        project: Project,
        *,
        record_usage=None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> DevDocsResult:
        """Scan, ask the provider for a plain-language summary, and save a
        new versioned snapshot. Raises ``NoProjectFolderError`` /
        ``ProviderNotReadyError`` as appropriate.

        ``on_chunk``, if given, streams partial response text as it arrives
        (see ``AIProvider.generate_stream``) instead of blocking silently
        for the whole reply."""
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. Add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )
        scan_result = self.scan(project)
        prompt = build_dev_docs_prompt(scan_result, project_name=project.name)
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
            response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        snapshot = self._snapshots.create(
            project_id=project.id,
            source_summary=scan_result.as_summary_dict(),
            ai_summary=response.text,
            provider=response.provider,
        )
        return DevDocsResult(
            scan=scan_result,
            response_text=response.text,
            provider=response.provider,
            snapshot=snapshot,
        )

    def latest(self, project_id: int) -> DevDocsSnapshot | None:
        return self._snapshots.latest_for_project(project_id)

    def history(self, project_id: int, limit: int = 20) -> list[DevDocsSnapshot]:
        """Newest-first, same shape as every other feature's history()."""
        return self._snapshots.list_for_project(project_id, limit=limit)
