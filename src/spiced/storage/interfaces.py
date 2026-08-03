"""Repository interfaces shared between local and remote implementations.

The architecture plan calls for a Local/Remote split so that, as later phases
land, per-project data (test cases, debug sessions, feedback, etc.) can be
read/written through the FastAPI backend instead of local SQLite once a
project is linked to a team — while unlinked ("Solo") projects keep using the
existing concrete ``storage/*Repository`` classes unchanged.

Phase A only introduces one entity that is remote from day one: teams
themselves have no local representation, since "who's on this team" only
makes sense on the shared backend. ``TeamRepository`` describes that surface
as a Protocol so ``spiced.backend_client.api_client.BackendClient`` (the only
implementation for now) can be swapped for a test double without every
caller depending on the httpx-based class directly. Later phases add
Local/Remote pairs for the entities named in the architecture plan; this
phase does not touch test_cases/debug_sessions/feedback/etc.
"""

from __future__ import annotations

from typing import Protocol


class TeamSummary(Protocol):
    id: str
    name: str


class TeamMemberSummary(Protocol):
    id: str
    team_id: str
    user_id: str | None
    invited_email: str | None
    role: str


class TeamProjectSummary(Protocol):
    id: str
    team_id: str
    project_uuid: str
    name: str


class TeamRepository(Protocol):
    """Operations Services.teams needs, independent of the HTTP transport."""

    def create_team(self, name: str) -> TeamSummary: ...

    def list_teams(self) -> list[TeamSummary]: ...

    def invite_member(
        self, team_id: str, email: str, role: str = "member"
    ) -> TeamMemberSummary: ...

    def list_members(self, team_id: str) -> list[TeamMemberSummary]: ...

    def link_project(self, team_id: str, project_uuid: str, name: str) -> TeamProjectSummary: ...

    def list_projects(self, team_id: str) -> list[TeamProjectSummary]: ...

    def unlink_project(self, team_id: str, project_uuid: str) -> None: ...
