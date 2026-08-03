"""Team CRUD, invite, and project-linking endpoint tests against SQLite."""

from __future__ import annotations

import uuid


def test_create_and_list_team(client, login_as):
    login_as(email="owner@example.com")

    response = client.post("/teams", json={"name": "Moonlit Depths Crew"})
    assert response.status_code == 201
    team = response.json()
    assert team["name"] == "Moonlit Depths Crew"

    listed = client.get("/teams")
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()] == [team["id"]]


def test_list_teams_only_returns_teams_you_belong_to(client, login_as):
    login_as(email="owner@example.com")
    client.post("/teams", json={"name": "Owner's Team"})

    login_as(email="outsider@example.com")
    response = client.get("/teams")
    assert response.status_code == 200
    assert response.json() == []


def test_invite_pending_user_then_resolves_on_login(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team A"}).json()

    invite = client.post(
        f"/teams/{team['id']}/invite", json={"email": "future@example.com"}
    )
    assert invite.status_code == 201
    body = invite.json()
    assert body["user_id"] is None
    assert body["invited_email"] == "future@example.com"
    assert body["joined_at"] is None

    members_before = client.get(f"/teams/{team['id']}/members").json()
    assert len(members_before) == 2

    login_as(email="future@example.com")
    resolved = client.get("/teams").json()
    assert any(t["id"] == team["id"] for t in resolved)

    members_after = client.get(f"/teams/{team['id']}/members").json()
    invited_member = next(m for m in members_after if m["invited_email"] == "future@example.com")
    assert invited_member["user_id"] is not None
    assert invited_member["joined_at"] is not None


def test_invite_existing_user_attaches_immediately(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team B"}).json()

    login_as(email="teammate@example.com")
    client.get("/teams")  # ensures the user row exists

    login_as(email="owner@example.com")
    invite = client.post(
        f"/teams/{team['id']}/invite", json={"email": "teammate@example.com"}
    )
    assert invite.status_code == 201
    body = invite.json()
    assert body["user_id"] is not None
    assert body["joined_at"] is not None


def test_duplicate_invite_is_rejected(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team C"}).json()
    client.post(f"/teams/{team['id']}/invite", json={"email": "dup@example.com"})
    second = client.post(f"/teams/{team['id']}/invite", json={"email": "dup@example.com"})
    assert second.status_code == 409


def test_non_member_cannot_see_team_details(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Private Team"}).json()

    login_as(email="stranger@example.com")
    response = client.get(f"/teams/{team['id']}/members")
    assert response.status_code == 403


def test_link_list_and_unlink_project(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team D"}).json()

    project_uuid = str(uuid.uuid4())
    link = client.post(
        f"/teams/{team['id']}/projects",
        json={"project_uuid": project_uuid, "name": "Moonlit Depths"},
    )
    assert link.status_code == 201
    assert link.json()["project_uuid"] == project_uuid

    listed = client.get(f"/teams/{team['id']}/projects")
    assert listed.status_code == 200
    assert [p["project_uuid"] for p in listed.json()] == [project_uuid]

    unlink = client.delete(f"/teams/{team['id']}/projects/{project_uuid}")
    assert unlink.status_code == 204

    listed_after = client.get(f"/teams/{team['id']}/projects")
    assert listed_after.json() == []


def test_relink_project_updates_name(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team E"}).json()
    project_uuid = str(uuid.uuid4())
    client.post(
        f"/teams/{team['id']}/projects", json={"project_uuid": project_uuid, "name": "Old Name"}
    )
    relinked = client.post(
        f"/teams/{team['id']}/projects", json={"project_uuid": project_uuid, "name": "New Name"}
    )
    assert relinked.status_code == 201
    assert relinked.json()["name"] == "New Name"

    listed = client.get(f"/teams/{team['id']}/projects").json()
    assert len(listed) == 1


def test_unlink_missing_project_returns_404(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team F"}).json()
    response = client.delete(f"/teams/{team['id']}/projects/{uuid.uuid4()}")
    assert response.status_code == 404


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
