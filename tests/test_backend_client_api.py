"""BackendClient tests. All HTTP is faked via httpx.MockTransport — no real
call is ever made to a running backend in tests.
"""

from __future__ import annotations

import httpx
import pytest

from spiced.backend_client.api_client import (
    BackendAPIError,
    BackendClient,
    NotAuthenticatedError,
)


def _client(handler, token: str | None = "jwt-abc") -> BackendClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return BackendClient(base_url="http://testserver", token=token, http_client=http_client)


def test_create_team_sends_bearer_token_and_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/teams"
        assert request.headers["Authorization"] == "Bearer jwt-abc"
        return httpx.Response(
            201,
            json={
                "id": "team-1",
                "name": "Moonlit Crew",
                "created_by": "user-1",
                "created_at": "2026-08-03T00:00:00Z",
            },
        )

    team = _client(handler).create_team("Moonlit Crew")
    assert team.id == "team-1"
    assert team.name == "Moonlit Crew"


def _team_json(team_id: str, name: str) -> dict:
    return {
        "id": team_id,
        "name": name,
        "created_by": "u1",
        "created_at": "2026-01-01T00:00:00Z",
    }


def test_list_teams_parses_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_team_json("t1", "A"), _team_json("t2", "B")])

    teams = _client(handler).list_teams()
    assert [t.id for t in teams] == ["t1", "t2"]


def test_link_and_list_project():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "link-1",
                    "team_id": "team-1",
                    "project_uuid": "proj-uuid",
                    "name": "Moonlit Depths",
                    "created_at": "2026-08-03T00:00:00Z",
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": "link-1",
                    "team_id": "team-1",
                    "project_uuid": "proj-uuid",
                    "name": "Moonlit Depths",
                    "created_at": "2026-08-03T00:00:00Z",
                }
            ],
        )

    client = _client(handler)
    linked = client.link_project("team-1", "proj-uuid", "Moonlit Depths")
    assert linked.project_uuid == "proj-uuid"
    projects = client.list_projects("team-1")
    assert projects[0].project_uuid == "proj-uuid"


def test_unlink_project_sends_delete():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(204)

    _client(handler).unlink_project("team-1", "proj-uuid")
    assert seen == {"method": "DELETE", "path": "/teams/team-1/projects/proj-uuid"}


def test_missing_token_raises_without_network_call():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should never be called without a token")

    with pytest.raises(NotAuthenticatedError):
        _client(handler, token=None).list_teams()


def test_401_response_raises_not_authenticated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "expired"})

    with pytest.raises(NotAuthenticatedError):
        _client(handler).list_teams()


def test_error_response_raises_backend_api_error_with_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "Not a member of this team."})

    with pytest.raises(BackendAPIError, match="Not a member of this team."):
        _client(handler).list_members("team-1")


def test_network_error_raises_backend_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(BackendAPIError, match="Could not reach the Spiced backend"):
        _client(handler).list_teams()


def test_set_token_updates_subsequent_requests():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer new-token"
        return httpx.Response(200, json=[])

    client = _client(handler, token="old-token")
    client.set_token("new-token")
    client.list_teams()
