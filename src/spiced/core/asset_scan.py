"""Asset Optimization Sweep use-case.

Orchestrates the read-only recursive scan in ``connectors.unity_scan`` and
optionally asks the AI provider for a plain-language summary. The scan step
alone works fully offline with no provider — exactly like Code Health's
local metrics — and never modifies or deletes anything under the project's
``Assets/`` folder; this is suggestions only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_asset_scan_prompt
from spiced.connectors.unity_scan import (
    OversizedAssetFinding,
    find_oversized_and_uncompressed,
    scan_references,
)
from spiced.storage.asset_scan_reports import AssetScanReport, AssetScanReportRepository
from spiced.storage.projects import Project

MAX_ORPHANS_IN_REPORT = 15


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class NoUnityFolderError(RuntimeError):
    """Raised when the project has no connected folder to scan."""


@dataclass(frozen=True)
class AssetScanFindings:
    oversized: list[OversizedAssetFinding] = field(default_factory=list)
    orphaned_assets: list[str] = field(default_factory=list)
    orphan_caveat: str = ""

    def as_summary_dict(self) -> dict:
        return {
            "oversized": [
                {"path": f.path, "size_bytes": f.size_bytes, "kind": f.kind, "reason": f.reason}
                for f in self.oversized
            ],
            "orphaned_assets": self.orphaned_assets,
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
        """Deterministic, local-only scan. Works with no AI provider."""
        if not project.path:
            raise NoUnityFolderError(
                "Connect a Unity folder for this project first (Projects screen)."
            )
        oversized = find_oversized_and_uncompressed(project.path)
        refs = scan_references(project.path)
        return AssetScanFindings(
            oversized=oversized,
            orphaned_assets=refs.orphaned_assets[:MAX_ORPHANS_IN_REPORT],
            orphan_caveat=refs.caveat,
        )

    def analyze(
        self, provider: AIProvider, project: Project, *, record_usage=None
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
        )
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
