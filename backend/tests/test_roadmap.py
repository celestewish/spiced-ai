"""Roadmap endpoint tests: public viewing, auth-gated submit/vote."""

from __future__ import annotations


def test_list_changelog_is_public_and_starts_empty(client):
    # No login_as call — viewing must need no login.
    response = client.get("/roadmap/changelog")
    assert response.status_code == 200
    assert response.json() == []


def test_create_and_list_changelog_entry_is_open(client):
    # POST /roadmap/changelog is intentionally open (no admin-role concept
    # yet) — see routers/roadmap.py's module docstring for why.
    response = client.post(
        "/roadmap/changelog",
        json={
            "version_or_phase_label": "Phase C",
            "title": "Test entry",
            "body": "Body text.",
        },
    )
    assert response.status_code == 201
    listed = client.get("/roadmap/changelog").json()
    assert len(listed) == 1
    assert listed[0]["title"] == "Test entry"
    assert listed[0]["version_or_phase_label"] == "Phase C"


def test_list_suggestions_is_public_and_starts_empty(client):
    response = client.get("/roadmap/suggestions")
    assert response.status_code == 200
    assert response.json() == []


def test_create_suggestion_requires_auth(client):
    response = client.post(
        "/roadmap/suggestions", json={"title": "Add dark mode", "body": "Please."}
    )
    assert response.status_code == 401


def test_vote_requires_auth(client):
    response = client.post("/roadmap/suggestions/does-not-exist/vote")
    assert response.status_code == 401


def test_submit_then_vote_then_unvote_suggestion(client, login_as):
    login_as(email="author@example.com")
    created = client.post(
        "/roadmap/suggestions", json={"title": "Add dark mode", "body": "Please."}
    ).json()
    assert created["vote_count"] == 0
    assert created["voted_by_me"] is False

    login_as(email="voter@example.com")
    vote_response = client.post(f"/roadmap/suggestions/{created['id']}/vote")
    assert vote_response.status_code == 204

    listed = client.get("/roadmap/suggestions").json()
    row = next(s for s in listed if s["id"] == created["id"])
    assert row["vote_count"] == 1
    assert row["voted_by_me"] is True  # still signed in as the voter

    unvote_response = client.delete(f"/roadmap/suggestions/{created['id']}/vote")
    assert unvote_response.status_code == 204
    listed_again = client.get("/roadmap/suggestions").json()
    row_again = next(s for s in listed_again if s["id"] == created["id"])
    assert row_again["vote_count"] == 0
    assert row_again["voted_by_me"] is False


def test_voting_twice_does_not_double_count(client, login_as):
    login_as(email="author2@example.com")
    created = client.post(
        "/roadmap/suggestions", json={"title": "Add light mode", "body": "Please."}
    ).json()

    login_as(email="voter2@example.com")
    client.post(f"/roadmap/suggestions/{created['id']}/vote")
    client.post(f"/roadmap/suggestions/{created['id']}/vote")

    listed = client.get("/roadmap/suggestions").json()
    row = next(s for s in listed if s["id"] == created["id"])
    assert row["vote_count"] == 1


def test_anonymous_viewer_never_sees_voted_by_me_true(client, login_as, logout):
    login_as(email="author3@example.com")
    created = client.post(
        "/roadmap/suggestions", json={"title": "Add controller support", "body": "Please."}
    ).json()
    login_as(email="voter3@example.com")
    client.post(f"/roadmap/suggestions/{created['id']}/vote")
    logout()

    # A plain, unauthenticated GET afterwards must not report anyone's vote
    # as "mine" — there's no "current user" to attribute it to.
    listed = client.get("/roadmap/suggestions").json()
    row = next(s for s in listed if s["id"] == created["id"])
    assert row["vote_count"] == 1
    assert row["voted_by_me"] is False
