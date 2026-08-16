"""Dependency & Plugin Update Checks use-case.

Reads a Unity project's own ``Packages/manifest.json`` and compares each
declared package version against the public Unity Package Registry
(``connectors.unity_package_registry``). The check itself works fully
offline-safe: a registry that can't be reached just yields "couldn't check"
entries rather than raising, matching every other local-scan feature's
"free, deterministic core, optional AI gloss on top" shape (Asset
Optimization Sweep, Code Health). Read-only — nothing about the project is
uploaded, only package names the developer already declared are looked up.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_dependency_check_prompt
from spiced.connectors.unity import manifest_path_for, read_manifest_versions
from spiced.connectors.unity_package_registry import (
    DEFAULT_BASE_URL,
    PackageCheckResult,
    check_packages,
)
from spiced.storage.dependency_check_reports import (
    DependencyCheckReport,
    DependencyCheckReportRepository,
)
from spiced.storage.projects import Project


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class NoUnityFolderError(RuntimeError):
    """Raised when the project has no connected folder to read a manifest from."""


class NoManifestError(RuntimeError):
    """Raised when the project has no ``Packages/manifest.json`` to read."""


@dataclass(frozen=True)
class DependencyCheckFindings:
    results: list[PackageCheckResult] = field(default_factory=list)

    @property
    def outdated_count(self) -> int:
        return sum(1 for r in self.results if r.outdated)

    @property
    def unchecked_count(self) -> int:
        return sum(1 for r in self.results if not r.checked)

    def as_summary_dict(self) -> dict:
        return {
            "results": [
                {
                    "name": r.name,
                    "installed_version": r.installed_version,
                    "latest_version": r.latest_version,
                    "outdated": r.outdated,
                    "checked": r.checked,
                    "note": r.note,
                }
                for r in self.results
            ]
        }


def check_dependencies(
    project: Project, base_url: str = DEFAULT_BASE_URL
) -> DependencyCheckFindings:
    """Deterministic, network-only (no AI) pass. Never raises on a network failure —
    only on a missing project folder/manifest, which are developer setup issues."""
    if not project.path:
        raise NoUnityFolderError(
            "Connect a Unity folder for this project first (Projects screen)."
        )
    manifest = manifest_path_for(project.path)
    if not manifest.is_file():
        raise NoManifestError(
            "No Packages/manifest.json found in this project — nothing to check yet."
        )
    installed = read_manifest_versions(manifest)
    return DependencyCheckFindings(results=check_packages(installed, base_url=base_url))


@dataclass(frozen=True)
class DependencyCheckReview:
    findings: DependencyCheckFindings
    response_text: str | None
    provider: str | None
    report: DependencyCheckReport | None


class DependencyCheckService:
    def __init__(self, reports: DependencyCheckReportRepository) -> None:
        self._reports = reports

    def check(self, project: Project) -> DependencyCheckFindings:
        return check_dependencies(project)

    def analyze(
        self,
        provider: AIProvider,
        project: Project,
        *,
        record_usage=None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> DependencyCheckReview:
        """Check, then ask the provider for optional plain-language commentary."""
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. You can still see the "
                "local version-check results without it. For a written summary, add its API "
                "key to a local .env file (see .env.example), or switch to the Mock provider "
                "in Settings."
            )
        findings = self.check(project)
        prompt = build_dependency_check_prompt(findings.results, project_name=project.name)
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
        return DependencyCheckReview(
            findings=findings,
            response_text=response.text,
            provider=response.provider,
            report=report,
        )

    def history(self, project_id: int, limit: int = 20) -> list[DependencyCheckReport]:
        return self._reports.list_for_project(project_id, limit=limit)
