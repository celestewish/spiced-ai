"""Event routing rule + notification preference endpoint tests (Phase J).

Scope reminder: these only test the routing *decision data* persistence --
no notification is ever delivered or displayed by this backend, that's
Phase K's Notification Center.
"""

from __future__ import annotations


def _make_team(client, login_as, name="Routing Team"):
    login_as(email="owner@example.com")
    return client.post("/teams", json={"name": name}).json()


def test_add_list_and_delete_routing_rule(client, login_as):
    team = _make_team(client, login_as)

    created = client.post(
        f"/teams/{team['id']}/routing-rules",
        json={"event_kind": "audio_checklist_gap", "discipline": "audio"},
    )
    assert created.status_code == 201
    rule_id = created.json()["id"]

    listed = client.get(f"/teams/{team['id']}/routing-rules")
    assert [r["event_kind"] for r in listed.json()] == ["audio_checklist_gap"]

    deleted = client.delete(f"/teams/{team['id']}/routing-rules/{rule_id}")
    assert deleted.status_code == 204
    assert client.get(f"/teams/{team['id']}/routing-rules").json() == []


def test_adding_duplicate_rule_is_idempotent(client, login_as):
    team = _make_team(client, login_as)
    body = {"event_kind": "animation_bug_finding", "discipline": "animation"}
    client.post(f"/teams/{team['id']}/routing-rules", json=body)
    client.post(f"/teams/{team['id']}/routing-rules", json=body)
    listed = client.get(f"/teams/{team['id']}/routing-rules").json()
    assert len(listed) == 1


def test_set_and_list_notification_preferences(client, login_as):
    team = _make_team(client, login_as)

    set_pref = client.put(
        f"/teams/{team['id']}/notification-preferences/me",
        json={"event_kind": "known_issue_opened", "enabled": False},
    )
    assert set_pref.status_code == 200
    assert set_pref.json()["enabled"] is False

    # Re-setting the same event kind updates in place rather than duplicating.
    client.put(
        f"/teams/{team['id']}/notification-preferences/me",
        json={"event_kind": "known_issue_opened", "enabled": True},
    )
    listed = client.get(f"/teams/{team['id']}/notification-preferences").json()
    matching = [p for p in listed if p["event_kind"] == "known_issue_opened"]
    assert len(matching) == 1
    assert matching[0]["enabled"] is True


def test_notification_preferences_are_visible_to_any_member(client, login_as):
    team = _make_team(client, login_as)
    client.put(
        f"/teams/{team['id']}/notification-preferences/me",
        json={"event_kind": "shader_performance_flag", "enabled": False},
    )
    invite = client.post(
        f"/teams/{team['id']}/invite", json={"email": "teammate@example.com"}
    ).json()
    assert invite["invited_email"] is None or invite["user_id"] is None

    login_as(email="teammate@example.com")
    listed = client.get(f"/teams/{team['id']}/notification-preferences")
    assert listed.status_code == 200
    assert any(p["event_kind"] == "shader_performance_flag" for p in listed.json())


def test_non_member_cannot_read_routing_rules(client, login_as):
    team = _make_team(client, login_as)
    login_as(email="stranger@example.com")
    response = client.get(f"/teams/{team['id']}/routing-rules")
    assert response.status_code == 403
