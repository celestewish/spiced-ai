"""Unified Task Board endpoint tests against SQLite (Phase J)."""

from __future__ import annotations

import uuid


def _make_team(client, login_as, name="Board Team"):
    login_as(email="owner@example.com")
    return client.post("/teams", json={"name": name}).json()


def test_create_and_list_tasks(client, login_as):
    team = _make_team(client, login_as)
    project_uuid = str(uuid.uuid4())

    created = client.post(
        f"/teams/{team['id']}/tasks",
        json={
            "title": "Fix flicker on hub scene",
            "description": "Reported by playtesters",
            "project_uuid": project_uuid,
            "assigned_discipline": "animation",
            "source_type": "animation",
            "source_ref": "empty-state:Hub.controller:12",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "open"
    assert body["assigned_discipline"] == "animation"
    assert body["source_ref"] == "empty-state:Hub.controller:12"

    listed = client.get(f"/teams/{team['id']}/tasks")
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()] == [body["id"]]

    scoped = client.get(f"/teams/{team['id']}/tasks", params={"project_uuid": project_uuid})
    assert len(scoped.json()) == 1
    other_scoped = client.get(
        f"/teams/{team['id']}/tasks", params={"project_uuid": str(uuid.uuid4())}
    )
    assert other_scoped.json() == []


def test_update_task_status_and_fields(client, login_as):
    team = _make_team(client, login_as)
    created = client.post(f"/teams/{team['id']}/tasks", json={"title": "Task A"}).json()

    updated = client.patch(
        f"/teams/{team['id']}/tasks/{created['id']}",
        json={"status": "in_progress", "assigned_discipline": "audio"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"
    assert updated.json()["assigned_discipline"] == "audio"

    invalid = client.patch(
        f"/teams/{team['id']}/tasks/{created['id']}", json={"status": "not-a-status"}
    )
    assert invalid.status_code == 422


def test_delete_task(client, login_as):
    team = _make_team(client, login_as)
    created = client.post(f"/teams/{team['id']}/tasks", json={"title": "Task B"}).json()

    deleted = client.delete(f"/teams/{team['id']}/tasks/{created['id']}")
    assert deleted.status_code == 204

    listed = client.get(f"/teams/{team['id']}/tasks")
    assert listed.json() == []


def test_non_member_cannot_touch_tasks(client, login_as):
    team = _make_team(client, login_as)
    login_as(email="stranger@example.com")
    response = client.post(f"/teams/{team['id']}/tasks", json={"title": "Nope"})
    assert response.status_code == 403


def test_update_missing_task_returns_404(client, login_as):
    team = _make_team(client, login_as)
    response = client.patch(
        f"/teams/{team['id']}/tasks/{uuid.uuid4()}", json={"status": "done"}
    )
    assert response.status_code == 404
