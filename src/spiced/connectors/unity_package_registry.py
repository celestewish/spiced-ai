"""Unity Package Registry client (read-only version lookups).

Dependency & Plugin Update Checks (Phase E, section 6) is the first place
Spiced makes an outbound network call beyond an AI provider or the team
backend: it queries the public Unity Package Registry — an npm-compatible
registry — to see whether packages already declared in the developer's own
``Packages/manifest.json`` have a newer version published. Nothing about the
project is ever sent; only the public package *names* the developer already
listed in their own manifest are looked up, one ``GET`` per package.

Verified against the real registry (2026-08, ``com.unity.textmeshpro`` and
``com.unity.timeline``): ``GET https://packages.unity.com/<package-name>``
returns ``200`` with an npm-registry-shaped JSON body —
``{"name": ..., "dist-tags": {"latest": "<version>"}, "versions": {"<version>": {...}, ...}, ...}``
— or ``404`` with ``{"error": "Package <name> not found"}`` for an unknown
name. This module reads ``dist-tags.latest`` as the authoritative "current"
version, falling back to the highest key under ``versions`` only if
``dist-tags`` is missing or empty.

Every network failure (offline development, a firewalled registry, a
timeout, an unexpected response shape) is caught here and turned into a
``PackageRegistryInfo``/``PackageCheckResult`` with ``error`` set rather than
raised — this feature must never crash or block the rest of the app just
because the network is unavailable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

DEFAULT_BASE_URL = "https://packages.unity.com"
DEFAULT_TIMEOUT_S = 10.0

# Dependency values that aren't a published registry version at all — local
# path, git, or plain URL references. The registry has nothing to compare
# these against, so they're skipped (reported as "not checked", not as an
# error) rather than sent as a bogus lookup.
_NON_REGISTRY_PREFIXES = ("file:", "git:", "git+", "http:", "https:", ".", "/")

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$")


@dataclass(frozen=True)
class PackageRegistryInfo:
    """Raw result of one registry lookup."""

    name: str
    latest_version: str | None
    found: bool
    error: str | None = None


def fetch_package_info(
    package_name: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> PackageRegistryInfo:
    """Look up one package's latest published version. Never raises."""
    url = f"{base_url.rstrip('/')}/{package_name}"
    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        return PackageRegistryInfo(
            name=package_name,
            latest_version=None,
            found=False,
            error=f"Couldn't reach the Unity Package Registry: {exc}",
        )

    if response.status_code == 404:
        return PackageRegistryInfo(
            name=package_name,
            latest_version=None,
            found=False,
            error="Not found in the public Unity Package Registry (may be a private/custom "
            "package the registry doesn't host).",
        )
    if response.status_code != 200:
        return PackageRegistryInfo(
            name=package_name,
            latest_version=None,
            found=False,
            error=f"Registry returned HTTP {response.status_code}.",
        )

    try:
        data = response.json()
    except ValueError:
        return PackageRegistryInfo(
            name=package_name,
            latest_version=None,
            found=False,
            error="Registry response wasn't valid JSON.",
        )
    if not isinstance(data, dict):
        return PackageRegistryInfo(
            name=package_name,
            latest_version=None,
            found=False,
            error="Unexpected registry response shape.",
        )

    latest = _extract_latest(data)
    if not latest:
        return PackageRegistryInfo(
            name=package_name,
            latest_version=None,
            found=True,
            error="Registry entry has no version information.",
        )
    return PackageRegistryInfo(name=package_name, latest_version=str(latest), found=True)


def _extract_latest(data: dict) -> str | None:
    dist_tags = data.get("dist-tags")
    if isinstance(dist_tags, dict):
        latest = dist_tags.get("latest")
        if isinstance(latest, str) and latest:
            return latest
    versions = data.get("versions")
    if isinstance(versions, dict) and versions:
        parseable = [v for v in versions if isinstance(v, str) and parse_version(v)]
        if parseable:
            return max(parseable, key=lambda v: parse_version(v))
        return sorted(versions)[-1]
    return None


def parse_version(version: str) -> tuple[int, int, int, int, str] | None:
    """Parse a semver-ish version string into a sortable tuple, or None.

    ``(major, minor, patch, is_stable, prerelease)`` — ``is_stable`` sorts a
    plain release (``1.2.3``) after a prerelease of the same core version
    (``1.2.3-pre.1``), matching semver precedence. The trailing prerelease
    string is compared lexically as a tie-breaker, which is a simplification
    of full semver prerelease-identifier comparison but is good enough for
    "is there something newer" — this module does not claim full semver
    compliance.
    """
    match = _VERSION_RE.match(version.strip())
    if not match:
        return None
    major, minor, patch, prerelease = match.groups()
    is_stable = 0 if prerelease else 1
    return (int(major), int(minor), int(patch), is_stable, prerelease or "")


def is_outdated(installed_version: str, latest_version: str) -> bool | None:
    """True if ``installed_version`` is older than ``latest_version``.

    None when either string isn't a parseable semver-ish version — reported
    to the developer as "couldn't compare" rather than guessed at.
    """
    installed = parse_version(installed_version)
    latest = parse_version(latest_version)
    if installed is None or latest is None:
        return None
    return installed < latest


@dataclass(frozen=True)
class PackageCheckResult:
    """One installed package compared against the registry."""

    name: str
    installed_version: str
    latest_version: str | None
    outdated: bool | None
    checked: bool
    note: str | None = None


def check_packages(
    installed: dict[str, str],
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> list[PackageCheckResult]:
    """Check every {name: version} pair from a manifest against the registry.

    Sequential, one request per package — Unity projects typically declare a
    few dozen packages at most, and this is a manual/on-demand check, not a
    background poller, so simplicity wins over concurrency here.
    """
    results: list[PackageCheckResult] = []
    for name in sorted(installed):
        installed_version = installed[name]
        if installed_version.startswith(_NON_REGISTRY_PREFIXES):
            results.append(
                PackageCheckResult(
                    name=name,
                    installed_version=installed_version,
                    latest_version=None,
                    outdated=None,
                    checked=False,
                    note="Not a registry version (local/git/URL dependency) — skipped.",
                )
            )
            continue
        info = fetch_package_info(name, base_url=base_url, timeout_s=timeout_s)
        if not info.found or not info.latest_version:
            results.append(
                PackageCheckResult(
                    name=name,
                    installed_version=installed_version,
                    latest_version=None,
                    outdated=None,
                    checked=False,
                    note=info.error,
                )
            )
            continue
        results.append(
            PackageCheckResult(
                name=name,
                installed_version=installed_version,
                latest_version=info.latest_version,
                outdated=is_outdated(installed_version, info.latest_version),
                checked=True,
            )
        )
    return results
