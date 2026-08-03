"""BackendClient tests for the Roadmap endpoints, mirroring
test_backend_client_api.py's MockTransport pattern. All HTTP is faked — no
real call is ever made to a running backend.
"""

from __future__ import annotations

import httpx

from spiced.backend_client.api_client import BackendClient, NotAuthenticatedError


def _client(handler, token: str | None = "jwt-abc") -> BackendClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return BackendClient(base_url="http://testserver", token=token, http_client=http_client)


def test_list_changelog_works_without_a_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/roadmap/changelog"
        assert "Authorization" not in request.headers
        return httpx.Response(
            200,
            json=[
                {
                    "id": "c1",
                    "version_or_phase_label": "Phase 1",
                    "title": "Unity Debugging Buddy",
                    "body": "...",
                    "published_at": "2026-01-01T00:00:00Z",
                }
            ],
        )

    entries = _client(handler, token=None).list_changelog()
    assert entries[0].id == "c1"
    assert entries[0].title == "Unity Debugging Buddy"


def test_list_suggestions_works_without_a_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/roadmap/suggestions"
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=[])

    assert _client(handler, token=None).list_suggestions() == []


def test_list_endpoints_still_attach_a_token_when_signed_in():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer jwt-abc"
        return httpx.Response(200, json=[])

    _client(handler).list_suggestions()


def test_create_suggestion_requires_a_token():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should never be called without a token")

    try:
        _client(handler, token=None).create_suggestion("title", "body")
    except NotAuthenticatedError:
        pass
    else:
        raise AssertionError("expected NotAuthenticatedError")


def test_create_suggestion_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/roadmap/suggestions"
        return httpx.Response(
            201,
            json={
                "id": "s1",
                "author_user_id": "u1",
                "title": "Add dark mode",
                "body": "Please",
                "created_at": "2026-08-03T00:00:00Z",
                "vote_count": 0,
                "voted_by_me": False,
            },
        )

    suggestion = _client(handler).create_suggestion("Add dark mode", "Please")
    assert suggestion.id == "s1"
    assert suggestion.vote_count == 0


def test_vote_and_unvote_send_expected_methods():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(204)

    client = _client(handler)
    client.vote_suggestion("s1")
    client.unvote_suggestion("s1")
    assert seen == [
        ("POST", "/roadmap/suggestions/s1/vote"),
        ("DELETE", "/roadmap/suggestions/s1/vote"),
    ]
