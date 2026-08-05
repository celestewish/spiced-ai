"""Notification Center endpoint tests against SQLite (Phase K, section 9 part 1).

Covers create/list/mark-read plus auth+membership gating. Delivery-cadence
bucketing itself is desktop-side pure logic (see
``tests/test_notification_center.py`` in the desktop test suite) -- this
file only exercises the backend storage/API surface.
"""

from __future__ import annotations


def _make_team_with_member(client, login_as, name="Notify Team"):
    """An owner plus one already-registered teammate, immediately attached
    (mirrors backend/tests/test_teams.py's
    test_invite_existing_user_attaches_immediately pattern -- the teammate
    must make one authenticated call first so their ``users`` row actually
    exists before being invited, otherwise the invite stays pending)."""
    teammate_id = login_as(email="teammate@example.com")
    client.get("/teams")
    owner_id = login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": name}).json()
    invite = client.post(
        f"/teams/{team['id']}/invite", json={"email": "teammate@example.com"}
    ).json()
    assert invite["user_id"] == teammate_id
    return team, owner_id, teammate_id


def test_create_list_and_mark_read(client, login_as):
    team, _owner_id, teammate_id = _make_team_with_member(client, login_as)

    created = client.post(
        f"/teams/{team['id']}/notifications",
        json={
            "recipient_user_id": teammate_id,
            "event_kind": "team_task_assigned",
            "title": "New task assigned to you",
            "body": "Fix the flicker on the hub scene.",
            "subject_type": "task",
            "subject_id": "abc-123",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["read_at"] is None
    assert body["recipient_user_id"] == teammate_id

    # The owner (creator, not recipient) doesn't see it in their own inbox.
    owner_inbox = client.get(f"/teams/{team['id']}/notifications")
    assert owner_inbox.json() == []

    login_as(email="teammate@example.com")
    teammate_inbox = client.get(f"/teams/{team['id']}/notifications")
    assert teammate_inbox.status_code == 200
    assert [n["id"] for n in teammate_inbox.json()] == [body["id"]]

    marked = client.post(f"/teams/{team['id']}/notifications/{body['id']}/read")
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None

    # Marking again is idempotent (stays read, doesn't error).
    marked_again = client.post(f"/teams/{team['id']}/notifications/{body['id']}/read")
    assert marked_again.status_code == 200
    assert marked_again.json()["read_at"] is not None


def test_most_recent_first(client, login_as):
    team, _owner_id, teammate_id = _make_team_with_member(client, login_as)
    for title in ("First", "Second", "Third"):
        client.post(
            f"/teams/{team['id']}/notifications",
            json={
                "recipient_user_id": teammate_id,
                "event_kind": "comment_posted",
                "title": title,
                "body": "…",
            },
        )
    login_as(email="teammate@example.com")
    listed = client.get(f"/teams/{team['id']}/notifications").json()
    assert [n["title"] for n in listed] == ["Third", "Second", "First"]


def test_recipient_must_be_a_team_member(client, login_as):
    team, _owner_id, _teammate_id = _make_team_with_member(client, login_as)
    response = client.post(
        f"/teams/{team['id']}/notifications",
        json={
            "recipient_user_id": "not-a-member-id",
            "event_kind": "comment_posted",
            "title": "Nope",
            "body": "…",
        },
    )
    assert response.status_code == 422


def test_non_member_cannot_create_or_list_notifications(client, login_as):
    team, _owner_id, teammate_id = _make_team_with_member(client, login_as)
    login_as(email="stranger@example.com")

    create = client.post(
        f"/teams/{team['id']}/notifications",
        json={
            "recipient_user_id": teammate_id,
            "event_kind": "comment_posted",
            "title": "Nope",
            "body": "…",
        },
    )
    assert create.status_code == 403

    listed = client.get(f"/teams/{team['id']}/notifications")
    assert listed.status_code == 403


def test_cannot_mark_someone_elses_notification_read(client, login_as):
    team, owner_id, teammate_id = _make_team_with_member(client, login_as)
    created = client.post(
        f"/teams/{team['id']}/notifications",
        json={
            "recipient_user_id": teammate_id,
            "event_kind": "comment_posted",
            "title": "For teammate only",
            "body": "…",
        },
    ).json()

    # Still logged in as owner (the creator) -- not the recipient.
    response = client.post(f"/teams/{team['id']}/notifications/{created['id']}/read")
    assert response.status_code == 404


def test_set_notification_preference_delivery_cadence(client, login_as):
    login_as(email="owner@example.com")
    team = client.post("/teams", json={"name": "Cadence Team"}).json()

    set_pref = client.put(
        f"/teams/{team['id']}/notification-preferences/me",
        json={"event_kind": "build_failed", "enabled": True, "delivery": "hourly"},
    )
    assert set_pref.status_code == 200
    assert set_pref.json()["delivery"] == "hourly"

    # Omitting delivery defaults to realtime.
    set_default = client.put(
        f"/teams/{team['id']}/notification-preferences/me",
        json={"event_kind": "comment_posted", "enabled": True},
    )
    assert set_default.json()["delivery"] == "realtime"

    # Re-saving updates the cadence in place.
    updated = client.put(
        f"/teams/{team['id']}/notification-preferences/me",
        json={"event_kind": "build_failed", "enabled": True, "delivery": "daily"},
    )
    listed = client.get(f"/teams/{team['id']}/notification-preferences").json()
    matching = [p for p in listed if p["event_kind"] == "build_failed"]
    assert len(matching) == 1
    assert matching[0]["delivery"] == "daily"
    assert updated.json()["delivery"] == "daily"
