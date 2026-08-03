"""Telemetry endpoint tests: no auth required, anonymous only."""

from __future__ import annotations


def test_create_telemetry_event_requires_no_auth(client):
    # No login_as call anywhere in this test — the endpoint must still work.
    response = client.post(
        "/telemetry",
        json={
            "anonymous_client_id": "11111111-1111-1111-1111-111111111111",
            "event_name": "debugging.crash_diagnosis_run",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["anonymous_client_id"] == "11111111-1111-1111-1111-111111111111"
    assert body["event_name"] == "debugging.crash_diagnosis_run"
    assert "id" in body
    assert "created_at" in body
    # No user/team field of any kind on the response — anonymous by design.
    assert "user_id" not in body
    assert "team_id" not in body


def test_telemetry_event_truncates_overly_long_fields(client):
    response = client.post(
        "/telemetry",
        json={"anonymous_client_id": "x" * 100, "event_name": "y" * 500},
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["anonymous_client_id"]) == 36
    assert len(body["event_name"]) == 200


def test_telemetry_event_rejects_missing_fields(client):
    response = client.post("/telemetry", json={"anonymous_client_id": "abc"})
    assert response.status_code == 422
