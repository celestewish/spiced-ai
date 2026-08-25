"""TriggerRule endpoint tests (Market-Viability Roadmap, Phase 4).

Scope reminder, same as test_notification_routing.py: this backend only
persists rule *configuration*. Evaluating a rule against an incoming event
is entirely a desktop-side concern (core.rules_engine.evaluate_rules).
"""

from __future__ import annotations


def _make_team(client, login_as, name="Rules Team"):
    login_as(email="owner@example.com")
    return client.post("/teams", json={"name": name}).json()


def test_add_list_and_delete_trigger_rule(client, login_as):
    team = _make_team(client, login_as)

    created = client.post(
        f"/teams/{team['id']}/trigger-rules",
        json={
            "event_kind": "audio.loudness_normalize",
            "min_severity": "warning",
            "action": "notify",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["event_kind"] == "audio.loudness_normalize"
    assert body["min_severity"] == "warning"
    assert body["action"] == "notify"
    assert body["action_params_json"] == "{}"
    assert body["enabled"] is True
    rule_id = body["id"]

    listed = client.get(f"/teams/{team['id']}/trigger-rules")
    assert [r["event_kind"] for r in listed.json()] == ["audio.loudness_normalize"]

    deleted = client.delete(f"/teams/{team['id']}/trigger-rules/{rule_id}")
    assert deleted.status_code == 204
    assert client.get(f"/teams/{team['id']}/trigger-rules").json() == []


def test_add_trigger_rule_with_action_params(client, login_as):
    team = _make_team(client, login_as)

    created = client.post(
        f"/teams/{team['id']}/trigger-rules",
        json={
            "event_kind": "animation_bug_finding",
            "min_severity": "warning",
            "action": "create_task",
            "action_params_json": '{"assigned_discipline": "animation"}',
        },
    )
    assert created.status_code == 201
    assert created.json()["action_params_json"] == '{"assigned_discipline": "animation"}'


def test_adding_duplicate_event_kind_and_action_is_idempotent(client, login_as):
    team = _make_team(client, login_as)
    body = {
        "event_kind": "vfx.shader_variant_analysis",
        "min_severity": "error",
        "action": "queue_changelog_note",
    }
    client.post(f"/teams/{team['id']}/trigger-rules", json=body)
    client.post(f"/teams/{team['id']}/trigger-rules", json=body)
    listed = client.get(f"/teams/{team['id']}/trigger-rules").json()
    assert len(listed) == 1


def test_same_event_kind_different_action_is_not_deduplicated(client, login_as):
    team = _make_team(client, login_as)
    client.post(
        f"/teams/{team['id']}/trigger-rules",
        json={
            "event_kind": "art.palette_drift",
            "min_severity": "warning",
            "action": "notify",
        },
    )
    client.post(
        f"/teams/{team['id']}/trigger-rules",
        json={
            "event_kind": "art.palette_drift",
            "min_severity": "warning",
            "action": "create_task",
        },
    )
    listed = client.get(f"/teams/{team['id']}/trigger-rules").json()
    assert len(listed) == 2


def test_non_member_cannot_read_trigger_rules(client, login_as):
    team = _make_team(client, login_as)
    login_as(email="stranger@example.com")
    response = client.get(f"/teams/{team['id']}/trigger-rules")
    assert response.status_code == 403


def test_delete_nonexistent_rule_returns_404(client, login_as):
    team = _make_team(client, login_as)
    response = client.delete(f"/teams/{team['id']}/trigger-rules/not-a-real-id")
    assert response.status_code == 404
