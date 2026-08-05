"""BackendClient tests for the Phase J Team/Task-Board/Comment/notification-
routing endpoints, mirroring test_backend_client_roadmap.py's MockTransport
pattern. All HTTP is faked -- no real call is ever made to a running backend.
"""

from __future__ import annotations

import httpx

from spiced.backend_client.api_client import BackendClient


def _client(handler, token: str | None = "jwt-abc") -> BackendClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return BackendClient(base_url="http://testserver", token=token, http_client=http_client)


def _task_row(**overrides):
    row = {
        "id": "task1",
        "team_id": "team1",
        "project_uuid": "proj-uuid",
        "title": "Fix flicker",
        "description": None,
        "status": "open",
        "assigned_discipline": "animation",
        "source_type": "animation",
        "source_ref": "empty-state:Hub.controller:12",
        "created_by_user_id": "u1",
        "created_at": "2026-08-04T00:00:00Z",
        "updated_at": "2026-08-04T00:00:00Z",
    }
    row.update(overrides)
    return row


def test_create_task_sends_expected_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(201, json=_task_row())

    client = _client(handler)
    task = client.create_task(
        "team1", "Fix flicker", project_uuid="proj-uuid",
        assigned_discipline="animation", source_type="animation",
        source_ref="empty-state:Hub.controller:12",
    )
    assert seen["path"] == "/teams/team1/tasks"
    assert task.id == "task1"
    assert task.assigned_discipline == "animation"
    assert task.source_ref == "empty-state:Hub.controller:12"


def test_list_tasks_with_project_filter_encodes_query():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/teams/team1/tasks"
        assert request.url.params["project_uuid"] == "proj-uuid"
        return httpx.Response(200, json=[_task_row()])

    tasks = _client(handler).list_tasks("team1", project_uuid="proj-uuid")
    assert len(tasks) == 1


def test_update_task_status():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        return httpx.Response(200, json=_task_row(status="in_progress"))

    task = _client(handler).update_task("team1", "task1", status_value="in_progress")
    assert task.status == "in_progress"


def test_delete_task_sends_delete():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(204)

    _client(handler).delete_task("team1", "task1")
    assert seen == [("DELETE", "/teams/team1/tasks/task1")]


def test_create_and_list_comments():
    def handler(request: httpx.Request) -> httpx.Response:
        row = {
            "id": "c1", "team_id": "team1", "subject_type": "task", "subject_id": "task1",
            "author_user_id": "u1", "body": "Looks good",
            "created_at": "2026-08-04T00:00:00Z",
        }
        if request.method == "POST":
            return httpx.Response(201, json=row)
        assert request.url.params["subject_type"] == "task"
        assert request.url.params["subject_id"] == "task1"
        return httpx.Response(200, json=[row])

    client = _client(handler)
    created = client.create_comment("team1", "task", "task1", "Looks good")
    assert created.body == "Looks good"
    listed = client.list_comments("team1", "task", "task1")
    assert len(listed) == 1


def test_set_my_discipline():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/teams/team1/members/me"
        assert request.method == "PATCH"
        return httpx.Response(
            200,
            json={
                "id": "m1", "team_id": "team1", "user_id": "u1", "invited_email": None,
                "email": "me@example.com", "role": "member", "discipline": "programmer",
                "joined_at": "2026-08-04T00:00:00Z", "created_at": "2026-08-04T00:00:00Z",
            },
        )

    member = _client(handler).set_my_discipline("team1", "programmer")
    assert member.discipline == "programmer"


def test_routing_rule_crud():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "r1", "team_id": "team1", "event_kind": "audio_checklist_gap",
                    "discipline": "audio", "created_at": "2026-08-04T00:00:00Z",
                },
            )
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(204)

    client = _client(handler)
    rule = client.add_routing_rule("team1", "audio_checklist_gap", "audio")
    assert rule.discipline == "audio"
    client.list_routing_rules("team1")
    client.delete_routing_rule("team1", "r1")
    assert ("DELETE", "/teams/team1/routing-rules/r1") in calls


def test_set_notification_preference():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/teams/team1/notification-preferences/me"
        return httpx.Response(
            200,
            json={
                "id": "p1", "team_id": "team1", "user_id": "u1",
                "event_kind": "known_issue_opened", "enabled": False,
                "created_at": "2026-08-04T00:00:00Z",
            },
        )

    pref = _client(handler).set_notification_preference("team1", "known_issue_opened", False)
    assert pref.enabled is False
