"""Small-Team Mode use-cases: teams, invites, and project linking.

Thin orchestration over BackendClient plus the local project row: keeps the
caller's JWT in sync with AuthService and mints a project's project_uuid the
first time it's linked to a team.
"""

from __future__ import annotations

from spiced.backend_client.api_client import BackendClient, Team, TeamMember, TeamProject
from spiced.core.auth_service import AuthService
from spiced.core.projects_service import ProjectsService


class TeamService:
    def __init__(
        self,
        auth: AuthService,
        projects: ProjectsService,
        api_client: BackendClient | None = None,
    ) -> None:
        self._auth = auth
        self._projects = projects
        self._client = api_client or BackendClient()

    def _synced_client(self) -> BackendClient:
        self._client.set_token(self._auth.access_token())
        return self._client

    def create_team(self, name: str) -> Team:
        return self._synced_client().create_team(name)

    def list_teams(self) -> list[Team]:
        return self._synced_client().list_teams()

    def invite_member(self, team_id: str, email: str, role: str = "member") -> TeamMember:
        return self._synced_client().invite_member(team_id, email, role)

    def list_members(self, team_id: str) -> list[TeamMember]:
        return self._synced_client().list_members(team_id)

    def link_active_project(self, team_id: str, project_id: int, name: str) -> TeamProject:
        project_uuid = self._projects.ensure_project_uuid(project_id)
        return self._synced_client().link_project(team_id, project_uuid, name)

    def list_projects(self, team_id: str) -> list[TeamProject]:
        return self._synced_client().list_projects(team_id)

    def unlink_project(self, team_id: str, project_uuid: str) -> None:
        self._synced_client().unlink_project(team_id, project_uuid)
