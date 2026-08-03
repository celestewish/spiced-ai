"""TeamService tests: orchestration over a fake BackendClient + real local project storage."""

from __future__ import annotations

from spiced.backend_client.api_client import Team, TeamMember, TeamProject
from spiced.backend_client.auth_client import AuthSession
from spiced.core.auth_service import AuthService
from spiced.core.projects_service import ProjectsService
from spiced.core.team_service import TeamService
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.settings import SettingsRepository


class _FakeAuthClient:
    def is_configured(self) -> bool:
        return True

    def log_in(self, email: str, password: str) -> AuthSession:
        return AuthSession(access_token="jwt-1", refresh_token="r1", user_id="u1", email=email)

    def sign_up(self, email: str, password: str) -> AuthSession:
        return self.log_in(email, password)


class _FakeBackendClient:
    def __init__(self) -> None:
        self.token: str | None = None
        self.linked: list[tuple[str, str, str]] = []

    def set_token(self, token: str | None) -> None:
        self.token = token

    def create_team(self, name: str) -> Team:
        return Team(id="team-1", name=name, created_by="u1", created_at="2026-08-03T00:00:00Z")

    def list_teams(self) -> list[Team]:
        return [
            Team(id="team-1", name="Crew", created_by="u1", created_at="2026-08-03T00:00:00Z")
        ]

    def invite_member(self, team_id: str, email: str, role: str = "member") -> TeamMember:
        return TeamMember(
            id="m1",
            team_id=team_id,
            user_id=None,
            invited_email=email,
            role=role,
            joined_at=None,
            created_at="2026-08-03T00:00:00Z",
        )

    def list_members(self, team_id: str) -> list[TeamMember]:
        return []

    def link_project(self, team_id: str, project_uuid: str, name: str) -> TeamProject:
        self.linked.append((team_id, project_uuid, name))
        return TeamProject(
            id="link-1",
            team_id=team_id,
            project_uuid=project_uuid,
            name=name,
            created_at="2026-08-03T00:00:00Z",
        )

    def list_projects(self, team_id: str) -> list[TeamProject]:
        return []

    def unlink_project(self, team_id: str, project_uuid: str) -> None:
        self.linked = [row for row in self.linked if row[1] != project_uuid]


def _setup():
    db = Database(":memory:")
    settings = SettingsRepository(db)
    auth = AuthService(settings, _FakeAuthClient())
    projects = ProjectsService(ProjectRepository(db))
    backend = _FakeBackendClient()
    team_service = TeamService(auth, projects, backend)
    return auth, projects, team_service, backend


def test_create_and_list_team_uses_current_token():
    auth, _projects, teams, backend = _setup()
    auth.log_in("dev@example.com", "hunter2")
    team = teams.create_team("Crew")
    assert team.id == "team-1"
    assert backend.token == "jwt-1"
    assert teams.list_teams()[0].name == "Crew"


def test_link_active_project_mints_project_uuid_once():
    auth, projects, teams, backend = _setup()
    auth.log_in("dev@example.com", "hunter2")
    project = projects.create_project("Moonlit Depths")
    assert project.project_uuid is None

    link = teams.link_active_project("team-1", project.id, project.name)
    minted = projects.get_project(project.id).project_uuid
    assert minted is not None
    assert link.project_uuid == minted
    assert backend.linked == [("team-1", minted, "Moonlit Depths")]

    # Linking again reuses the same project_uuid rather than minting a new one.
    teams.link_active_project("team-1", project.id, project.name)
    assert projects.get_project(project.id).project_uuid == minted


def test_unlink_project_removes_from_backend():
    auth, projects, teams, backend = _setup()
    auth.log_in("dev@example.com", "hunter2")
    project = projects.create_project("Moonlit Depths")
    teams.link_active_project("team-1", project.id, project.name)
    project_uuid = projects.get_project(project.id).project_uuid

    teams.unlink_project("team-1", project_uuid)
    assert backend.linked == []


def test_invite_member_delegates_to_backend():
    auth, _projects, teams, _backend = _setup()
    auth.log_in("dev@example.com", "hunter2")
    member = teams.invite_member("team-1", "teammate@example.com")
    assert member.invited_email == "teammate@example.com"
