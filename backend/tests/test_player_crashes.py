"""Player Crash & Error Reporting endpoint tests against SQLite.

Covers: no-auth POST, project-must-be-team-linked constraint, payload size
capping, auth+membership-required GET.
"""

from __future__ import annotations

import uuid

from app.routers.player_crashes import (
    MAX_ERROR_TYPE_CHARS,
    MAX_MESSAGE_CHARS,
    MAX_STACK_EXCERPT_CHARS,
)


def _team_and_project(client):
    team = client.post("/teams", json={"name": "Moonlit Depths Crew"}).json()
    project_uuid = str(uuid.uuid4())
    client.post(
        f"/teams/{team['id']}/projects",
        json={"project_uuid": project_uuid, "name": "Moonlit Depths"},
    )
    return team["id"], project_uuid


def _crash_body(**overrides):
    body = {
        "error_type": "NullReferenceException",
        "message": "Object reference not set to an instance of an object.",
        "stack_excerpt": "at InventoryManager.AddItem (Item item) [0x0002a]",
        "app_version": "1.2.0",
        "occurred_at": "2026-08-04T21:13:05Z",
    }
    body.update(overrides)
    return body


def test_post_crash_report_requires_no_auth(client, login_as):
    login_as(email="owner@example.com")
    _, project_uuid = _team_and_project(client)

    response = client.post(f"/projects/{project_uuid}/player-crashes", json=_crash_body())
    assert response.status_code == 201
    body = response.json()
    assert body["project_uuid"] == project_uuid
    assert body["error_type"] == "NullReferenceException"


def test_post_crash_report_works_without_any_bearer_token(client, login_as, logout):
    login_as(email="owner@example.com")
    _, project_uuid = _team_and_project(client)
    logout()  # simulate a real player's request: no Spiced account at all

    response = client.post(f"/projects/{project_uuid}/player-crashes", json=_crash_body())
    assert response.status_code == 201


def test_post_crash_report_rejects_unlinked_project(client):
    unlinked_uuid = str(uuid.uuid4())
    response = client.post(f"/projects/{unlinked_uuid}/player-crashes", json=_crash_body())
    assert response.status_code == 404


def test_post_crash_report_truncates_oversized_fields(client, login_as):
    login_as(email="owner@example.com")
    _, project_uuid = _team_and_project(client)

    response = client.post(
        f"/projects/{project_uuid}/player-crashes",
        json=_crash_body(
            error_type="E" * 300,  # over the 200-char storage cap, under the 500 pydantic cap
            message="M" * 3000,  # over the 2000-char storage cap, under the 4000 pydantic cap
            stack_excerpt="S" * 5000,  # over the 4000-char storage cap, under the 20000 cap
        ),
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["error_type"]) == MAX_ERROR_TYPE_CHARS
    assert len(body["message"]) == MAX_MESSAGE_CHARS
    assert len(body["stack_excerpt"]) == MAX_STACK_EXCERPT_CHARS


def test_post_crash_report_rejects_wildly_oversized_payload(client, login_as):
    """Pydantic's Field(max_length=...) rejects a request far beyond even
    the loose outer bound outright — this is never an open, unbounded
    write endpoint."""
    login_as(email="owner@example.com")
    _, project_uuid = _team_and_project(client)

    response = client.post(
        f"/projects/{project_uuid}/player-crashes",
        json=_crash_body(message="M" * 100_000),
    )
    assert response.status_code == 422


def test_get_crash_reports_requires_auth(client):
    project_uuid = str(uuid.uuid4())
    response = client.get(f"/projects/{project_uuid}/player-crashes")
    assert response.status_code == 401


def test_get_crash_reports_requires_team_membership(client, login_as):
    login_as(email="owner@example.com")
    _, project_uuid = _team_and_project(client)
    client.post(f"/projects/{project_uuid}/player-crashes", json=_crash_body())

    login_as(email="stranger@example.com")
    response = client.get(f"/projects/{project_uuid}/player-crashes")
    assert response.status_code == 403


def test_get_crash_reports_visible_to_team_members(client, login_as):
    login_as(email="owner@example.com")
    team_id, project_uuid = _team_and_project(client)
    client.post(f"/teams/{team_id}/invite", json={"email": "teammate@example.com"})
    client.post(f"/projects/{project_uuid}/player-crashes", json=_crash_body())
    client.post(
        f"/projects/{project_uuid}/player-crashes",
        json=_crash_body(error_type="IndexOutOfRangeException"),
    )

    login_as(email="teammate@example.com")
    response = client.get(f"/projects/{project_uuid}/player-crashes")
    assert response.status_code == 200
    reports = response.json()
    assert len(reports) == 2
    error_types = {r["error_type"] for r in reports}
    assert error_types == {"NullReferenceException", "IndexOutOfRangeException"}


def test_get_crash_reports_for_unlinked_project_is_404(client, login_as):
    login_as(email="owner@example.com")
    unlinked_uuid = str(uuid.uuid4())
    response = client.get(f"/projects/{unlinked_uuid}/player-crashes")
    assert response.status_code == 404
