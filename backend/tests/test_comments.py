"""Comment Threads endpoint tests against SQLite (Phase J)."""

from __future__ import annotations


def _make_team(client, login_as, name="Comment Team"):
    login_as(email="owner@example.com")
    return client.post("/teams", json={"name": name}).json()


def test_create_and_list_comments_on_a_task(client, login_as):
    team = _make_team(client, login_as)
    task = client.post(f"/teams/{team['id']}/tasks", json={"title": "Task"}).json()

    created = client.post(
        f"/teams/{team['id']}/comments",
        json={"subject_type": "task", "subject_id": task["id"], "body": "Looks good to me"},
    )
    assert created.status_code == 201
    assert created.json()["body"] == "Looks good to me"

    listed = client.get(
        f"/teams/{team['id']}/comments",
        params={"subject_type": "task", "subject_id": task["id"]},
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_comments_on_known_issue_are_scoped_by_subject_id(client, login_as):
    team = _make_team(client, login_as)
    client.post(
        f"/teams/{team['id']}/comments",
        json={"subject_type": "known_issue", "subject_id": "42", "body": "Regressed again"},
    )
    client.post(
        f"/teams/{team['id']}/comments",
        json={"subject_type": "known_issue", "subject_id": "99", "body": "Unrelated"},
    )
    listed = client.get(
        f"/teams/{team['id']}/comments", params={"subject_type": "known_issue", "subject_id": "42"}
    )
    bodies = [c["body"] for c in listed.json()]
    assert bodies == ["Regressed again"]


def test_empty_comment_body_rejected(client, login_as):
    team = _make_team(client, login_as)
    response = client.post(
        f"/teams/{team['id']}/comments",
        json={"subject_type": "known_issue", "subject_id": "1", "body": "   "},
    )
    assert response.status_code == 422


def test_invalid_subject_type_rejected(client, login_as):
    team = _make_team(client, login_as)
    response = client.post(
        f"/teams/{team['id']}/comments",
        json={"subject_type": "not-a-real-type", "subject_id": "1", "body": "hi"},
    )
    assert response.status_code == 422


def test_non_member_cannot_comment(client, login_as):
    team = _make_team(client, login_as)
    login_as(email="stranger@example.com")
    response = client.post(
        f"/teams/{team['id']}/comments",
        json={"subject_type": "known_issue", "subject_id": "1", "body": "hi"},
    )
    assert response.status_code == 403
