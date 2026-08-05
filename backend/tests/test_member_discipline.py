"""Discipline self-service + owner-set path tests (Phase J, Role-Based Dashboards)."""

from __future__ import annotations


def test_invite_can_set_discipline(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team"}).json()
    invite = client.post(
        f"/teams/{team['id']}/invite",
        json={"email": "artist@example.com", "role": "member", "discipline": "artist"},
    )
    assert invite.status_code == 201
    assert invite.json()["discipline"] == "artist"


def test_self_service_discipline_update(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team"}).json()

    response = client.patch(f"/teams/{team['id']}/members/me", json={"discipline": "programmer"})
    assert response.status_code == 200
    assert response.json()["discipline"] == "programmer"

    members = client.get(f"/teams/{team['id']}/members").json()
    assert members[0]["discipline"] == "programmer"


def test_owner_can_set_another_members_discipline(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team"}).json()
    invite = client.post(
        f"/teams/{team['id']}/invite", json={"email": "teammate@example.com"}
    ).json()

    updated = client.patch(
        f"/teams/{team['id']}/members/{invite['id']}", json={"discipline": "audio"}
    )
    assert updated.status_code == 200
    assert updated.json()["discipline"] == "audio"


def test_clear_discipline_with_null(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Team"}).json()
    client.patch(f"/teams/{team['id']}/members/me", json={"discipline": "design"})
    cleared = client.patch(f"/teams/{team['id']}/members/me", json={"discipline": None})
    assert cleared.status_code == 200
    assert cleared.json()["discipline"] is None
