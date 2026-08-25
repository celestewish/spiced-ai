"""Role-Based Permissions + Audit Log tests (Market-Viability Roadmap,
Phase 6): require_role gating on invite/remove-member/team-billing, the
new remove_member endpoint, and AuditLogEntry rows for every gated (and
several ungated) mutation in routers.teams.
"""

from __future__ import annotations


def _team_with_two_members(client, login_as, *, second_role="member"):
    """An owner plus one other real, already-registered member at the
    given role -- mirrors test_notifications.py's _make_team_with_member
    pattern (the invitee must make one authenticated call first so their
    users row exists, otherwise the invite stays pending by email)."""
    member_id = login_as(email="member@example.com")
    client.get("/teams")
    owner_id = login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()
    client.post(
        f"/teams/{team['id']}/invite",
        json={"email": "member@example.com", "role": second_role},
    )
    return team, owner_id, member_id


def test_owner_can_invite_as_admin_or_member(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()

    admin_invite = client.post(
        f"/teams/{team['id']}/invite", json={"email": "admin@example.com", "role": "admin"}
    )
    assert admin_invite.status_code == 201
    assert admin_invite.json()["role"] == "admin"

    member_invite = client.post(
        f"/teams/{team['id']}/invite", json={"email": "member@example.com"}
    )
    assert member_invite.status_code == 201
    assert member_invite.json()["role"] == "member"


def test_cannot_invite_someone_as_owner(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()

    response = client.post(
        f"/teams/{team['id']}/invite", json={"email": "wannabe@example.com", "role": "owner"}
    )

    assert response.status_code == 422


def test_invite_rejects_unknown_role(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()

    response = client.post(
        f"/teams/{team['id']}/invite", json={"email": "x@example.com", "role": "superadmin"}
    )

    assert response.status_code == 422


def test_plain_member_cannot_invite(client, login_as):
    team, _owner_id, _member_id = _team_with_two_members(client, login_as, second_role="member")
    login_as(email="member@example.com")

    response = client.post(
        f"/teams/{team['id']}/invite", json={"email": "someone@example.com"}
    )

    assert response.status_code == 403


def test_admin_can_invite(client, login_as):
    team, _owner_id, _admin_id = _team_with_two_members(client, login_as, second_role="admin")
    login_as(email="member@example.com")  # this member was invited as admin

    response = client.post(
        f"/teams/{team['id']}/invite", json={"email": "someone@example.com"}
    )

    assert response.status_code == 201


def test_owner_can_remove_a_member(client, login_as):
    team, owner_id, member_id = _team_with_two_members(client, login_as)
    login_as(user_id=owner_id, email="owner@example.com")
    member_row = next(
        m for m in client.get(f"/teams/{team['id']}/members").json() if m["user_id"] == member_id
    )

    response = client.delete(f"/teams/{team['id']}/members/{member_row['id']}")

    assert response.status_code == 204
    remaining = client.get(f"/teams/{team['id']}/members").json()
    assert all(m["id"] != member_row["id"] for m in remaining)


def test_plain_member_cannot_remove_another_member(client, login_as):
    member_id = login_as(email="member@example.com")
    client.get("/teams")
    second_id = login_as(email="second@example.com")
    client.get("/teams")
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()
    client.post(f"/teams/{team['id']}/invite", json={"email": "member@example.com"})
    client.post(f"/teams/{team['id']}/invite", json={"email": "second@example.com"})

    login_as(user_id=member_id, email="member@example.com")
    second_row = next(
        m for m in client.get(f"/teams/{team['id']}/members").json() if m["user_id"] == second_id
    )

    response = client.delete(f"/teams/{team['id']}/members/{second_row['id']}")

    assert response.status_code == 403


def test_cannot_remove_yourself(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()
    owner_row = client.get(f"/teams/{team['id']}/members").json()[0]

    response = client.delete(f"/teams/{team['id']}/members/{owner_row['id']}")

    assert response.status_code == 422


def test_cannot_remove_the_owner(client, login_as):
    team, owner_id, _member_id = _team_with_two_members(client, login_as, second_role="admin")
    owner_row = next(
        m for m in client.get(f"/teams/{team['id']}/members").json() if m["user_id"] == owner_id
    )
    login_as(email="member@example.com")  # the admin

    response = client.delete(f"/teams/{team['id']}/members/{owner_row['id']}")

    assert response.status_code == 422


def test_remove_nonexistent_member_returns_404(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()

    response = client.delete(f"/teams/{team['id']}/members/not-a-real-id")

    assert response.status_code == 404


# --- Audit log ---------------------------------------------------------


def test_team_created_and_invite_are_audited(client, login_as):
    owner_id = login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()
    client.post(f"/teams/{team['id']}/invite", json={"email": "member@example.com"})

    log = client.get(f"/teams/{team['id']}/audit-log").json()
    actions = [entry["action"] for entry in log]

    assert "team.created" in actions
    assert "member.invited" in actions
    assert all(entry["actor_user_id"] == owner_id for entry in log)


def test_remove_member_is_audited(client, login_as):
    team, owner_id, member_id = _team_with_two_members(client, login_as)
    login_as(user_id=owner_id, email="owner@example.com")
    member_row = next(
        m for m in client.get(f"/teams/{team['id']}/members").json() if m["user_id"] == member_id
    )
    client.delete(f"/teams/{team['id']}/members/{member_row['id']}")

    log = client.get(f"/teams/{team['id']}/audit-log").json()
    removed = next(e for e in log if e["action"] == "member.removed")
    assert removed["target_id"] == member_row["id"]


def test_project_link_and_unlink_are_audited(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()
    client.post(
        f"/teams/{team['id']}/projects",
        json={"project_uuid": "proj-1", "name": "Demo"},
    )
    client.delete(f"/teams/{team['id']}/projects/proj-1")

    log = client.get(f"/teams/{team['id']}/audit-log").json()
    actions = [entry["action"] for entry in log]
    assert "project.linked" in actions
    assert "project.unlinked" in actions


def test_discipline_changes_are_audited(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()
    client.patch(f"/teams/{team['id']}/members/me", json={"discipline": "programmer"})

    log = client.get(f"/teams/{team['id']}/audit-log").json()
    entry = next(e for e in log if e["action"] == "member.discipline_set")
    assert '"programmer"' in entry["metadata_json"]


def test_audit_log_requires_admin_role(client, login_as):
    team, _owner_id, _member_id = _team_with_two_members(client, login_as, second_role="member")
    login_as(email="member@example.com")

    response = client.get(f"/teams/{team['id']}/audit-log")

    assert response.status_code == 403


def test_audit_log_readable_by_admin(client, login_as):
    team, _owner_id, _admin_id = _team_with_two_members(client, login_as, second_role="admin")
    login_as(email="member@example.com")  # the admin

    response = client.get(f"/teams/{team['id']}/audit-log")

    assert response.status_code == 200


def test_non_member_cannot_see_audit_log(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Crew"}).json()

    login_as(email="stranger@example.com")
    response = client.get(f"/teams/{team['id']}/audit-log")

    assert response.status_code == 403
