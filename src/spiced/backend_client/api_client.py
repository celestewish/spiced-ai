"""Thin HTTP client for the Spiced backend's team endpoints.

Every call attaches the caller's Supabase JWT as a Bearer token; the backend
verifies it against Supabase Auth on each request (see backend/app/auth.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from spiced.backend_client import config


class BackendAPIError(RuntimeError):
    """Raised when the Spiced backend rejects or fails a request."""


class NotAuthenticatedError(BackendAPIError):
    """Raised when a call is made without a token (caller isn't logged in)."""


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    created_by: str
    created_at: str


@dataclass(frozen=True)
class TeamMember:
    id: str
    team_id: str
    user_id: str | None
    invited_email: str | None
    role: str
    joined_at: str | None
    created_at: str
    # Best-available contact address (invite address, or the joined user's
    # verified email) — added in Phase B for Team Mode prompt context.
    # Defaults to None so existing call sites/fakes built before this field
    # existed keep working.
    email: str | None = None


@dataclass(frozen=True)
class TeamProject:
    id: str
    team_id: str
    project_uuid: str
    name: str
    created_at: str


@dataclass(frozen=True)
class TeamSessionSummary:
    id: str
    team_id: str
    project_uuid: str
    user_id: str
    started_at: str
    ended_at: str
    summary_text: str
    created_at: str


class BackendClient:
    """Talks to the Spiced backend's ``/teams`` routes on behalf of one user."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = (base_url or config.backend_base_url()).rstrip("/")
        self._token = token
        self._http = http_client or httpx.Client(timeout=15.0)
        self._owns_http = http_client is None

    def set_token(self, token: str | None) -> None:
        self._token = token

    def create_team(self, name: str) -> Team:
        payload = self._request("POST", "/teams", json={"name": name})
        return _team(payload)

    def list_teams(self) -> list[Team]:
        payload = self._request("GET", "/teams")
        return [_team(row) for row in payload]

    def invite_member(self, team_id: str, email: str, role: str = "member") -> TeamMember:
        payload = self._request(
            "POST", f"/teams/{team_id}/invite", json={"email": email, "role": role}
        )
        return _member(payload)

    def list_members(self, team_id: str) -> list[TeamMember]:
        payload = self._request("GET", f"/teams/{team_id}/members")
        return [_member(row) for row in payload]

    def link_project(self, team_id: str, project_uuid: str, name: str) -> TeamProject:
        payload = self._request(
            "POST",
            f"/teams/{team_id}/projects",
            json={"project_uuid": project_uuid, "name": name},
        )
        return _project(payload)

    def list_projects(self, team_id: str) -> list[TeamProject]:
        payload = self._request("GET", f"/teams/{team_id}/projects")
        return [_project(row) for row in payload]

    def unlink_project(self, team_id: str, project_uuid: str) -> None:
        self._request("DELETE", f"/teams/{team_id}/projects/{project_uuid}")

    def post_session_summary(
        self, team_id: str, project_uuid: str, started_at: str, ended_at: str, summary_text: str
    ) -> TeamSessionSummary:
        payload = self._request(
            "POST",
            f"/teams/{team_id}/projects/{project_uuid}/sessions",
            json={"started_at": started_at, "ended_at": ended_at, "summary_text": summary_text},
        )
        return _session_summary(payload)

    def list_session_summaries(self, team_id: str, project_uuid: str) -> list[TeamSessionSummary]:
        payload = self._request("GET", f"/teams/{team_id}/projects/{project_uuid}/sessions")
        return [_session_summary(row) for row in payload]

    def _request(self, method: str, path: str, json: dict | None = None):
        if not self._token:
            raise NotAuthenticatedError("Sign in to Spiced Team Mode first.")
        try:
            response = self._http.request(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._token}"},
                json=json,
            )
        except httpx.HTTPError as exc:
            raise BackendAPIError(f"Could not reach the Spiced backend: {exc}") from exc

        if response.status_code == 401:
            raise NotAuthenticatedError("Your session has expired. Sign in again.")
        if response.status_code >= 400:
            raise BackendAPIError(_error_message(response))
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def close(self) -> None:
        if self._owns_http:
            self._http.close()


def _error_message(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if detail:
        return str(detail)
    return f"Spiced backend request failed (HTTP {response.status_code})."


def _team(row: dict) -> Team:
    return Team(
        id=row["id"],
        name=row["name"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _member(row: dict) -> TeamMember:
    return TeamMember(
        id=row["id"],
        team_id=row["team_id"],
        user_id=row.get("user_id"),
        invited_email=row.get("invited_email"),
        email=row.get("email"),
        role=row["role"],
        joined_at=row.get("joined_at"),
        created_at=row["created_at"],
    )


def _project(row: dict) -> TeamProject:
    return TeamProject(
        id=row["id"],
        team_id=row["team_id"],
        project_uuid=row["project_uuid"],
        name=row["name"],
        created_at=row["created_at"],
    )


def _session_summary(row: dict) -> TeamSessionSummary:
    return TeamSessionSummary(
        id=row["id"],
        team_id=row["team_id"],
        project_uuid=row["project_uuid"],
        user_id=row["user_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        summary_text=row["summary_text"],
        created_at=row["created_at"],
    )
