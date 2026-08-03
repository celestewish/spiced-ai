"""Session-summary endpoint tests against SQLite, mirroring test_teams.py."""

from __future__ import annotations

import uuid


def _team_and_project(client):
    team = client.post("/teams", json={"name": "Moonlit Depths Crew"}).json()
    project_uuid = str(uuid.uuid4())
    client.post(
        f"/teams/{team['id']}/projects",
        json={"project_uuid": project_uuid, "name": "Moonlit Depths"},
    )
    return team["id"], project_uuid


def test_post_and_list_session_summary(client, login_as):
    login_as(email="owner@example.com")
    team_id, project_uuid = _team_and_project(client)

    response = client.post(
        f"/teams/{team_id}/projects/{project_uuid}/sessions",
        json={
            "started_at": "2026-08-03T09:00:00Z",
            "ended_at": "2026-08-03T11:00:00Z",
            "summary_text": "Tested the dash bug; fixed the pause menu freeze; open: onboarding.",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["team_id"] == team_id
    assert body["project_uuid"] == project_uuid
    assert "pause menu" in body["summary_text"]

    listed = client.get(f"/teams/{team_id}/projects/{project_uuid}/sessions")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == body["id"]


def test_session_summaries_are_visible_to_teammates(client, login_as):
    login_as(email="owner@example.com")
    team_id, project_uuid = _team_and_project(client)
    client.post(f"/teams/{team_id}/invite", json={"email": "teammate@example.com"})

    client.post(
        f"/teams/{team_id}/projects/{project_uuid}/sessions",
        json={
            "started_at": "2026-08-03T09:00:00Z",
            "ended_at": "2026-08-03T10:00:00Z",
            "summary_text": "Recap from the owner.",
        },
    )

    login_as(email="teammate@example.com")
    listed = client.get(f"/teams/{team_id}/projects/{project_uuid}/sessions")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["summary_text"] == "Recap from the owner."


def test_non_member_cannot_post_or_list_session_summaries(client, login_as):
    login_as(email="owner@example.com")
    team_id, project_uuid = _team_and_project(client)

    login_as(email="stranger@example.com")
    post_response = client.post(
        f"/teams/{team_id}/projects/{project_uuid}/sessions",
        json={
            "started_at": "2026-08-03T09:00:00Z",
            "ended_at": "2026-08-03T10:00:00Z",
            "summary_text": "Should not be allowed.",
        },
    )
    assert post_response.status_code == 403

    get_response = client.get(f"/teams/{team_id}/projects/{project_uuid}/sessions")
    assert get_response.status_code == 403


def test_team_member_email_reflects_pending_then_joined_state(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team With Emails"}).json()

    invite = client.post(
        f"/teams/{team['id']}/invite", json={"email": "future@example.com"}
    )
    assert invite.json()["email"] == "future@example.com"

    login_as(email="future@example.com")
    members = client.get(f"/teams/{team['id']}/members").json()
    resolved = next(m for m in members if m["user_id"] is not None and m["role"] == "member")
    assert resolved["email"] == "future@example.com"
