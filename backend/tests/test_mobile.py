"""Companion Mobile View (Phase L, section 9 part 2, Stretch tier) tests.

Covers: auth gating (no token -> 401, non-member -> 403), read-only HTML
content for a team member, HTML-escaping of user-controlled content, and --
structurally, not just by convention -- that this router defines no
mutating (POST/PUT/PATCH/DELETE) route at all. Also directly exercises
``app.auth.get_current_user_for_html``'s header-vs-query-token fallback
logic; the Supabase call itself is mocked, same as every other backend test
here -- these never hit the live Supabase project.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.auth import get_current_user_for_html, get_or_create_user
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.routers import mobile as mobile_router
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from tests.conftest import TestingSessionLocal


class _MobileUserState:
    user_id: str | None = None
    email: str | None = None


_mobile_state = _MobileUserState()


def _override_get_current_user_for_html(db: Session = Depends(get_db)):
    if _mobile_state.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No test user logged in."
        )
    return get_or_create_user(db, _mobile_state.user_id, _mobile_state.email)


app.dependency_overrides[get_current_user_for_html] = _override_get_current_user_for_html


@pytest.fixture
def login_as_mobile(login_as):
    """Same shape as conftest's ``login_as``, but also authenticates the
    Mobile Companion View's own dependency (``get_current_user_for_html``,
    not overridden by conftest's global ``login_as`` override) as the same
    user."""

    def _login(email: str | None = None) -> str:
        user_id = login_as(email=email)
        _mobile_state.user_id = user_id
        _mobile_state.email = email or f"{user_id}@example.com"
        return user_id

    yield _login
    _mobile_state.user_id = None
    _mobile_state.email = None


def _team_and_project(client):
    team = client.post("/teams", json={"name": "Moonlit Depths Crew"}).json()
    project_uuid = str(uuid.uuid4())
    client.post(
        f"/teams/{team['id']}/projects",
        json={"project_uuid": project_uuid, "name": "Moonlit Depths"},
    )
    return team["id"], project_uuid


# --- Router shape: read-only, no mutating routes ----------------------------


def test_mobile_router_has_no_mutating_routes():
    mutating = {"POST", "PUT", "PATCH", "DELETE"}
    for route in mobile_router.router.routes:
        methods = getattr(route, "methods", set()) or set()
        assert not (methods & mutating), f"{route.path} allows {methods & mutating}"


def test_mobile_router_only_defines_safe_http_methods():
    for route in mobile_router.router.routes:
        methods = getattr(route, "methods", set()) or set()
        assert methods <= {"GET", "HEAD", "OPTIONS"}


def test_mobile_router_has_at_least_one_route():
    """Guards against the two tests above vacuously passing on an empty
    router if someone accidentally strips the route out later."""
    assert len(mobile_router.router.routes) >= 1


# --- Auth gating -------------------------------------------------------------


def test_mobile_view_requires_auth(client):
    response = client.get("/mobile/teams/some-team-id")
    assert response.status_code == 401


def test_mobile_view_requires_team_membership(client, login_as_mobile):
    login_as_mobile(email="owner@example.com")
    team_id, _ = _team_and_project(client)

    login_as_mobile(email="stranger@example.com")
    response = client.get(f"/mobile/teams/{team_id}")
    assert response.status_code == 403


# --- Content -----------------------------------------------------------------


def test_mobile_view_shows_team_name_and_notifications(client, login_as_mobile):
    owner_id = login_as_mobile(email="owner@example.com")
    team_id, _project_uuid = _team_and_project(client)

    client.post(
        f"/teams/{team_id}/notifications",
        json={
            "recipient_user_id": owner_id,
            "event_kind": "build_failed",
            "title": "Nightly build failed",
            "body": "Compile error in PlayerController.cs",
        },
    )

    response = client.get(f"/mobile/teams/{team_id}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Moonlit Depths Crew" in body
    assert "Nightly build failed" in body
    assert "Compile error in PlayerController.cs" in body


def test_mobile_view_shows_player_crash_reports(client, login_as_mobile):
    login_as_mobile(email="owner@example.com")
    team_id, project_uuid = _team_and_project(client)
    client.post(
        f"/projects/{project_uuid}/player-crashes",
        json={
            "error_type": "NullReferenceException",
            "message": "Object reference not set to an instance of an object.",
            "occurred_at": "2026-08-04T21:13:05Z",
        },
    )

    response = client.get(f"/mobile/teams/{team_id}")
    assert response.status_code == 200
    assert "NullReferenceException" in response.text


def test_mobile_view_narrows_to_one_project_uuid(client, login_as_mobile):
    login_as_mobile(email="owner@example.com")
    team_id, project_a = _team_and_project(client)
    project_b = str(uuid.uuid4())
    client.post(
        f"/teams/{team_id}/projects", json={"project_uuid": project_b, "name": "Second Project"}
    )
    client.post(
        f"/projects/{project_a}/player-crashes",
        json={
            "error_type": "ProjectAError",
            "message": "from project A",
            "occurred_at": "2026-08-04T21:13:05Z",
        },
    )
    client.post(
        f"/projects/{project_b}/player-crashes",
        json={
            "error_type": "ProjectBError",
            "message": "from project B",
            "occurred_at": "2026-08-04T21:13:05Z",
        },
    )

    response = client.get(f"/mobile/teams/{team_id}", params={"project_uuid": project_a})
    assert response.status_code == 200
    assert "ProjectAError" in response.text
    assert "ProjectBError" not in response.text


def test_mobile_view_empty_states(client, login_as_mobile):
    login_as_mobile(email="owner@example.com")
    team_id, _ = _team_and_project(client)

    response = client.get(f"/mobile/teams/{team_id}")
    assert response.status_code == 200
    assert "No notifications yet." in response.text
    assert "No player crash reports." in response.text
    assert "No open tasks." in response.text


def test_mobile_view_html_escapes_user_content():
    """Titles/bodies come from user-controlled data (notification titles,
    crash messages) -- confirm the page-builder escapes them rather than
    injecting raw HTML."""
    from app.routers.mobile import _page

    rendered = _page("Team <script>", '<div>"quoted" & <b>bold</b></div>')
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


# --- get_current_user_for_html: header vs. query-param fallback ------------


def test_get_current_user_for_html_prefers_header_over_query_token():
    db = TestingSessionLocal()
    try:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="header-token")
        with patch(
            "app.auth._fetch_supabase_user",
            new=AsyncMock(return_value={"id": "u-header", "email": "header@example.com"}),
        ) as mock_fetch:
            user = asyncio.run(
                get_current_user_for_html(
                    token="query-token", credentials=creds, db=db, settings=get_settings()
                )
            )
        assert user.id == "u-header"
        assert mock_fetch.await_args.args[0] == "header-token"
    finally:
        db.close()


def test_get_current_user_for_html_falls_back_to_query_token():
    db = TestingSessionLocal()
    try:
        with patch(
            "app.auth._fetch_supabase_user",
            new=AsyncMock(return_value={"id": "u-query", "email": "query@example.com"}),
        ) as mock_fetch:
            user = asyncio.run(
                get_current_user_for_html(
                    token="query-token", credentials=None, db=db, settings=get_settings()
                )
            )
        assert user.id == "u-query"
        assert mock_fetch.await_args.args[0] == "query-token"
    finally:
        db.close()


def test_get_current_user_for_html_raises_without_header_or_query():
    db = TestingSessionLocal()
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                get_current_user_for_html(
                    token=None, credentials=None, db=db, settings=get_settings()
                )
            )
        assert exc_info.value.status_code == 401
    finally:
        db.close()
