"""Tests for the Unity Package Registry client.

All httpx calls are mocked — these tests never make a real network request.
The real registry's response shape was verified manually against
https://packages.unity.com/com.unity.textmeshpro and
https://packages.unity.com/com.unity.timeline during development; these
fixtures mirror that shape (dist-tags.latest, versions map, 404 error body).
"""

from __future__ import annotations

import httpx
import pytest

from spiced.connectors.unity_package_registry import (
    PackageRegistryInfo,
    check_packages,
    fetch_package_info,
    is_outdated,
    parse_version,
)


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, raise_json: bool = False):
        self.status_code = status_code
        self._json_data = json_data
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._json_data


class _FakeClient:
    def __init__(self, response: _FakeResponse | None = None, raise_error: Exception | None = None):
        self._response = response
        self._raise_error = raise_error
        self.requested_urls: list[str] = []

    def __call__(self, timeout):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        self.requested_urls.append(url)
        if self._raise_error:
            raise self._raise_error
        return self._response


# --- fetch_package_info ------------------------------------------------------


def test_fetch_package_info_reads_dist_tags_latest(monkeypatch):
    response = _FakeResponse(
        200,
        {
            "name": "com.unity.textmeshpro",
            "dist-tags": {"latest": "3.2.0-pre.15"},
            "versions": {"3.2.0-pre.15": {}, "3.0.6": {}},
        },
    )
    fake_client = _FakeClient(response)
    monkeypatch.setattr(httpx, "Client", fake_client)

    info = fetch_package_info("com.unity.textmeshpro")
    assert info == PackageRegistryInfo(
        name="com.unity.textmeshpro", latest_version="3.2.0-pre.15", found=True
    )
    assert fake_client.requested_urls == ["https://packages.unity.com/com.unity.textmeshpro"]


def test_fetch_package_info_falls_back_to_versions_map(monkeypatch):
    versions = {"1.2.0": {}, "1.8.12": {}}
    response = _FakeResponse(200, {"name": "com.unity.timeline", "versions": versions})
    monkeypatch.setattr(httpx, "Client", _FakeClient(response))

    info = fetch_package_info("com.unity.timeline")
    assert info.found is True
    assert info.latest_version == "1.8.12"


def test_fetch_package_info_404_is_not_found(monkeypatch):
    response = _FakeResponse(404, {"error": "Package com.unity.nope not found"})
    monkeypatch.setattr(httpx, "Client", _FakeClient(response))

    info = fetch_package_info("com.unity.nope")
    assert info.found is False
    assert info.latest_version is None
    assert "not found" in info.error.lower() or "private" in info.error.lower()


def test_fetch_package_info_network_failure_never_raises(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _FakeClient(raise_error=httpx.ConnectError("refused")))

    info = fetch_package_info("com.unity.timeline")
    assert info.found is False
    assert "reach" in info.error.lower()


def test_fetch_package_info_invalid_json_is_handled(monkeypatch):
    response = _FakeResponse(200, raise_json=True)
    monkeypatch.setattr(httpx, "Client", _FakeClient(response))

    info = fetch_package_info("com.unity.timeline")
    assert info.found is False
    assert "json" in info.error.lower()


def test_fetch_package_info_non_200_non_404(monkeypatch):
    response = _FakeResponse(500)
    monkeypatch.setattr(httpx, "Client", _FakeClient(response))

    info = fetch_package_info("com.unity.timeline")
    assert info.found is False
    assert "500" in info.error


# --- parse_version / is_outdated ---------------------------------------------


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.2.3", (1, 2, 3, 1, "")),
        ("1.2.3-pre.1", (1, 2, 3, 0, "pre.1")),
        ("not-a-version", None),
        ("1.2", None),
    ],
)
def test_parse_version(version, expected):
    assert parse_version(version) == expected


def test_is_outdated_true_when_installed_is_lower():
    assert is_outdated("1.0.0", "1.2.0") is True


def test_is_outdated_false_when_installed_is_current():
    assert is_outdated("1.2.0", "1.2.0") is False


def test_is_outdated_stable_beats_prerelease_of_same_core_version():
    assert is_outdated("1.2.0-pre.1", "1.2.0") is True
    assert is_outdated("1.2.0", "1.2.0-pre.1") is False


def test_is_outdated_none_when_unparseable():
    assert is_outdated("not-a-version", "1.2.0") is None


# --- check_packages -----------------------------------------------------------


def test_check_packages_skips_non_registry_dependencies(monkeypatch):
    calls = []

    def fake_fetch(name, base_url, timeout_s):
        calls.append(name)
        return PackageRegistryInfo(name=name, latest_version="9.9.9", found=True)

    monkeypatch.setattr(
        "spiced.connectors.unity_package_registry.fetch_package_info", fake_fetch
    )
    installed = {
        "com.unity.timeline": "1.0.0",
        "com.mycompany.local": "file:../MyLocalPackage",
        "com.mycompany.git": "git+https://example.com/repo.git",
    }
    results = check_packages(installed)
    assert calls == ["com.unity.timeline"]
    by_name = {r.name: r for r in results}
    assert by_name["com.unity.timeline"].checked is True
    assert by_name["com.unity.timeline"].outdated is True
    assert by_name["com.mycompany.local"].checked is False
    assert by_name["com.mycompany.git"].checked is False


def test_check_packages_reports_unchecked_on_registry_failure(monkeypatch):
    def fake_fetch(name, base_url, timeout_s):
        return PackageRegistryInfo(name=name, latest_version=None, found=False, error="offline")

    monkeypatch.setattr(
        "spiced.connectors.unity_package_registry.fetch_package_info", fake_fetch
    )
    results = check_packages({"com.unity.timeline": "1.0.0"})
    assert len(results) == 1
    assert results[0].checked is False
    assert results[0].note == "offline"
