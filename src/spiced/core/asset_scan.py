"""Asset Optimization Sweep use-case.

Orchestrates the read-only recursive scan for the project's engine
(``connectors.unity_scan``/``godot_scan``+``godot_scene_scan``/``unreal_scan``)
and optionally asks the AI provider for a plain-language summary. The scan
step alone works fully offline with no provider — exactly like Code Health's
local metrics — and never modifies or deletes anything under the project's
own scanned folder; this is suggestions only.

**Why a shared ``AssetFinding`` dataclass instead of passing each engine's
own oversized-asset type straight through.** The three engines' own
dataclasses don't line up: Unity's and Godot's ``OversizedAssetFinding`` both
carry ``path/size_bytes/kind/reason``, but Unreal's
``OversizedBinaryAssetFinding`` has no ``reason`` field at all (it can only
ever know a file's size/extension, never why that's worth flagging — see
``connectors.unreal_scan``'s module docstring). Feeding that straight into
code that unconditionally reads ``.reason`` (as ``ai.prompt_templates``' asset
-scan formatter used to) raises ``AttributeError`` the first time an Unreal
project runs this scan. ``AssetFinding`` normalizes all three into one shape,
synthesizing a ``reason`` for Unreal's binary findings, so every caller above
this module handles exactly one type.

Godot alone also has a second, unrelated concept -- broken ``.tscn`` scene
references (``connectors.godot_scene_scan.scan_broken_references``) -- with
no Unity or Unreal equivalent; it's surfaced as its own
``AssetScanFindings.broken_scene_references`` field, left empty for the
other two engines.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_asset_scan_prompt
from spiced.connectors import godot_scan, godot_scene_scan, unity_scan, unreal_scan
from spiced.core.engine_dispatch import ENGINE_GODOT, ENGINE_UNREAL
from spiced.storage.asset_scan_reports import AssetScanReport, AssetScanReportRepository
from spiced.storage.projects import Project

MAX_ORPHANS_IN_REPORT = 15

# Unreal's OversizedBinaryAssetFinding has no reason field (see module
# docstring) -- this is the synthesized explanation for why the file is
# flagged, applied uniformly since the real reason (compression/import
# settings) can't be determined without the Unreal Editor itself.
_UNREAL_BINARY_REASON = (
    "Unreal's packaged binary format can't be inspected further than size and extension "
    "without the Editor itself — open it there to check its import/compression settings."
)


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class NoProjectFolderError(RuntimeError):
    """Raised when the project has no connected folder to scan."""


@dataclass(frozen=True)
class AssetFinding:
    """Engine-agnostic oversized/uncompressed-asset finding — see module
    docstring for why this exists instead of passing each engine's own
    connector dataclass straight through."""

    path: str
    size_bytes: int
    kind: str
    reason: str


@dataclass(frozen=True)
class AssetScanFindings:
    oversized: list[AssetFinding] = field(default_factory=list)
    orphaned_assets: list[str] = field(default_factory=list)
    orphan_caveat: str = ""
    # Godot only ("scene_path -> missing_resource_path" strings) -- see
    # module docstring. Always [] for Unity/Unreal.
    broken_scene_references: list[str] = field(default_factory=list)

    def as_summary_dict(self) -> dict:
        return {
            "oversized": [
                {"path": f.path, "size_bytes": f.size_bytes, "kind": f.kind, "reason": f.reason}
                for f in self.oversized
            ],
            "orphaned_assets": self.orphaned_assets,
            "broken_scene_references": self.broken_scene_references,
        }


@dataclass(frozen=True)
class AssetScanReview:
    findings: AssetScanFindings
    response_text: str | None
    provider: str | None
    report: AssetScanReport | None


class AssetScanService:
    def __init__(self, reports: AssetScanReportRepository) -> None:
        self._reports = reports

    def scan(self, project: Project) -> AssetScanFindings:
        """Deterministic, local-only scan. Works with no AI provider.

        Dispatches on ``project.engine`` — see module docstring for why each
        engine's own finding shape is normalized into ``AssetFinding`` here
        rather than passed straight through."""
        if not project.path:
            raise NoProjectFolderError(
                f"Connect a {project.engine} folder for this project first (Projects screen)."
            )
        if project.engine == ENGINE_GODOT:
            return self._scan_godot(project.path)
        if project.engine == ENGINE_UNREAL:
            return self._scan_unreal(project.path)
        return self._scan_unity(project.path)

    def _scan_unity(self, project_path: str) -> AssetScanFindings:
        oversized = unity_scan.find_oversized_and_uncompressed(project_path)
        refs = unity_scan.scan_references(project_path)
        return AssetScanFindings(
            oversized=[
                AssetFinding(path=f.path, size_bytes=f.size_bytes, kind=f.kind, reason=f.reason)
                for f in oversized
            ],
            orphaned_assets=refs.orphaned_assets[:MAX_ORPHANS_IN_REPORT],
            orphan_caveat=refs.caveat,
        )

    def _scan_godot(self, project_path: str) -> AssetScanFindings:
        oversized = godot_scan.find_oversized_and_uncompressed(project_path)
        broken = godot_scene_scan.scan_broken_references(project_path)
        return AssetScanFindings(
            oversized=[
                AssetFinding(path=f.path, size_bytes=f.size_bytes, kind=f.kind, reason=f.reason)
                for f in oversized
            ],
            broken_scene_references=[
                f"{b.scene_path} -> {b.missing_resource_path}" for b in broken
            ],
        )

    def _scan_unreal(self, project_path: str) -> AssetScanFindings:
        binaries = unreal_scan.find_oversized_binary_assets(project_path)
        loose = unreal_scan.find_loose_uncompressed_source_assets(project_path)
        oversized = [
            AssetFinding(
                path=f.path, size_bytes=f.size_bytes, kind=f.kind, reason=_UNREAL_BINARY_REASON
            )
            for f in binaries
        ] + [
            AssetFinding(path=f.path, size_bytes=f.size_bytes, kind=f.kind, reason=f.reason)
            for f in loose
        ]
        oversized.sort(key=lambda f: f.size_bytes, reverse=True)
        return AssetScanFindings(oversized=oversized)

    def analyze(
        self,
        provider: AIProvider,
        project: Project,
        *,
        record_usage=None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> AssetScanReview:
        """Scan, then ask the provider for a plain-language summary, and save it."""
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. You can still see the "
                "local scan findings without it. For a written summary, add its API key to a "
                "local .env file (see .env.example), or switch to the Mock provider in Settings."
            )
        findings = self.scan(project)
        prompt = build_asset_scan_prompt(
            findings.oversized,
            findings.orphaned_assets,
            orphan_caveat=findings.orphan_caveat,
            project_name=project.name,
            engine=project.engine,
            broken_scene_references=findings.broken_scene_references,
        )
        if on_chunk is not None:
            response = provider.generate_stream(prompt, on_chunk)
        else:
            response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        report = self._reports.create(
            project_id=project.id,
            findings=findings.as_summary_dict(),
            ai_summary=response.text,
            provider=response.provider,
        )
        return AssetScanReview(
            findings=findings,
            response_text=response.text,
            provider=response.provider,
            report=report,
        )

    def history(self, project_id: int, limit: int = 20) -> list[AssetScanReport]:
        return self._reports.list_for_project(project_id, limit=limit)
