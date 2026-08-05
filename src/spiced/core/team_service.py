"""Small-Team Mode use-cases: teams, invites, and project linking.

Thin orchestration over BackendClient plus the local project row: keeps the
caller's JWT in sync with AuthService and mints a project's project_uuid the
first time it's linked to a team.
"""

from __future__ import annotations

from spiced.backend_client.api_client import (
    BackendClient,
    PlayerCrashReport,
    Team,
    TeamMember,
    TeamProject,
    TeamSessionSummary,
)
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

    # --- Team Mode prompt context + Session Summaries (Phase B) ------------

    def find_team_for_project(self, project_uuid: str) -> Team | None:
        """Which of the signed-in user's teams (if any) has this project linked.

        The client only stores a project's ``project_uuid`` locally, not
        which team it belongs to, so this checks each team the user is a
        member of. Small-Team Mode expects a handful of teams per user, so
        this stays cheap in practice.
        """
        for team in self.list_teams():
            projects = self._synced_client().list_projects(team.id)
            if any(p.project_uuid == project_uuid for p in projects):
                return team
        return None

    def list_other_members(self, team_id: str) -> list[TeamMember]:
        """Teammates on ``team_id`` other than the signed-in user — used to
        build the roster passed into Team Mode prompt context."""
        user = self._auth.current_user()
        members = self.list_members(team_id)
        if user is None:
            return members
        return [m for m in members if m.user_id != user.id]

    def post_session_summary(
        self, project_uuid: str, started_at: str, ended_at: str, summary_text: str
    ) -> TeamSessionSummary | None:
        """Post a session summary to the team backend, if this project is
        team-linked. Returns None (and posts nothing) if it isn't."""
        team = self.find_team_for_project(project_uuid)
        if team is None:
            return None
        return self._synced_client().post_session_summary(
            team.id, project_uuid, started_at, ended_at, summary_text
        )

    def list_session_summaries(self, project_uuid: str) -> list[TeamSessionSummary]:
        team = self.find_team_for_project(project_uuid)
        if team is None:
            return []
        return self._synced_client().list_session_summaries(team.id, project_uuid)

    # --- Player Crash & Error Reporting (Phase G) ---------------------------

    def list_player_crashes(self, project_uuid: str) -> list[PlayerCrashReport]:
        """Crash reports real players sent in for this team-linked project.

        The backend itself checks team membership (404s if the project
        isn't team-linked at all, 403s if the signed-in user isn't a
        member) — this is a thin, unfiltered pass-through.
        """
        return self._synced_client().list_player_crashes(project_uuid)
