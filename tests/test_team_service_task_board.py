"""TeamService tests for the Phase J Unified Task Board / Comment Threads /
discipline / notification-routing wiring, over a fake BackendClient (same
style as test_team_service.py)."""

from __future__ import annotations

from spiced.backend_client.api_client import (
    Comment,
    EventRoutingRule,
    NotificationPreference,
    Team,
    TeamMember,
    TeamProject,
    TeamTask,
)
from spiced.backend_client.auth_client import AuthSession
from spiced.core.auth_service import AuthService
from spiced.core.projects_service import ProjectsService
from spiced.core.team_service import TeamService
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository
from spiced.storage.settings import SettingsRepository

PROJECT_UUID = "proj-uuid-1"


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
        self.tasks: list[TeamTask] = []
        self.comments: list[Comment] = []
        self.routing_rules: list[EventRoutingRule] = []
        self.preferences: list[NotificationPreference] = []
        self.members: list[TeamMember] = [
            TeamMember(
                id="m1", team_id="team-1", user_id="u1", invited_email=None, role="owner",
                discipline="animation", joined_at="2026-08-04T00:00:00Z",
                created_at="2026-08-04T00:00:00Z",
            )
        ]

    def set_token(self, token: str | None) -> None:
        self.token = token

    def list_teams(self) -> list[Team]:
        return [Team(id="team-1", name="Crew", created_by="u1", created_at="2026-08-04T00:00:00Z")]

    def list_projects(self, team_id: str) -> list[TeamProject]:
        return [
            TeamProject(
                id="link-1", team_id=team_id, project_uuid=PROJECT_UUID, name="Demo",
                created_at="2026-08-04T00:00:00Z",
            )
        ]

    def list_members(self, team_id: str) -> list[TeamMember]:
        return self.members

    def set_my_discipline(self, team_id, discipline):
        self.members[0] = TeamMember(
            id="m1", team_id=team_id, user_id="u1", invited_email=None, role="owner",
            discipline=discipline, joined_at="2026-08-04T00:00:00Z",
            created_at="2026-08-04T00:00:00Z",
        )
        return self.members[0]

    def create_task(self, team_id, title, *, description=None, project_uuid=None,
                     assigned_discipline=None, source_type="manual", source_ref=None):
        task = TeamTask(
            id=f"task-{len(self.tasks) + 1}", team_id=team_id, project_uuid=project_uuid,
            title=title, description=description, status="open",
            assigned_discipline=assigned_discipline, source_type=source_type,
            source_ref=source_ref, created_by_user_id="u1",
            created_at="2026-08-04T00:00:00Z", updated_at="2026-08-04T00:00:00Z",
        )
        self.tasks.append(task)
        return task

    def list_tasks(self, team_id, project_uuid=None):
        tasks = [t for t in self.tasks if t.team_id == team_id]
        if project_uuid:
            tasks = [t for t in tasks if t.project_uuid == project_uuid]
        return tasks

    def update_task(self, team_id, task_id, *, title=None, description=None,
                     status_value=None, assigned_discipline=None):
        for i, t in enumerate(self.tasks):
            if t.id == task_id:
                updated = TeamTask(
                    id=t.id, team_id=t.team_id, project_uuid=t.project_uuid,
                    title=title or t.title, description=description or t.description,
                    status=status_value or t.status,
                    assigned_discipline=assigned_discipline or t.assigned_discipline,
                    source_type=t.source_type, source_ref=t.source_ref,
                    created_by_user_id=t.created_by_user_id, created_at=t.created_at,
                    updated_at="2026-08-04T01:00:00Z",
                )
                self.tasks[i] = updated
                return updated
        raise KeyError(task_id)

    def delete_task(self, team_id, task_id):
        self.tasks = [t for t in self.tasks if t.id != task_id]

    def create_comment(self, team_id, subject_type, subject_id, body):
        comment = Comment(
            id=f"c{len(self.comments) + 1}", team_id=team_id, subject_type=subject_type,
            subject_id=subject_id, author_user_id="u1", body=body,
            created_at="2026-08-04T00:00:00Z",
        )
        self.comments.append(comment)
        return comment

    def list_comments(self, team_id, subject_type, subject_id):
        return [
            c for c in self.comments
            if c.team_id == team_id and c.subject_type == subject_type
            and c.subject_id == subject_id
        ]

    def list_routing_rules(self, team_id):
        return [r for r in self.routing_rules if r.team_id == team_id]

    def add_routing_rule(self, team_id, event_kind, discipline):
        rule = EventRoutingRule(
            id=f"r{len(self.routing_rules) + 1}", team_id=team_id, event_kind=event_kind,
            discipline=discipline, created_at="2026-08-04T00:00:00Z",
        )
        self.routing_rules.append(rule)
        return rule

    def delete_routing_rule(self, team_id, rule_id):
        self.routing_rules = [r for r in self.routing_rules if r.id != rule_id]

    def list_notification_preferences(self, team_id):
        return [p for p in self.preferences if p.team_id == team_id]

    def set_notification_preference(self, team_id, event_kind, enabled):
        pref = NotificationPreference(
            id=f"p{len(self.preferences) + 1}", team_id=team_id, user_id="u1",
            event_kind=event_kind, enabled=enabled, created_at="2026-08-04T00:00:00Z",
        )
        self.preferences.append(pref)
        return pref


def _setup():
    db = Database(":memory:")
    settings = SettingsRepository(db)
    auth = AuthService(settings, _FakeAuthClient())
    projects = ProjectsService(ProjectRepository(db))
    backend = _FakeBackendClient()
    team_service = TeamService(auth, projects, backend)
    auth.log_in("dev@example.com", "hunter2")
    return team_service, backend


def test_send_finding_to_team_board_creates_prefilled_task():
    teams, backend = _setup()
    task = teams.send_finding_to_team_board(
        PROJECT_UUID, "Empty state: Hub.controller",
        description="No motion assigned",
        assigned_discipline="animation",
        source_type="animation",
        source_ref="empty-state:Hub.controller:12",
    )
    assert task is not None
    assert task.assigned_discipline == "animation"
    assert task.source_ref == "empty-state:Hub.controller:12"
    assert task.project_uuid == PROJECT_UUID
    assert backend.tasks[0].title == "Empty state: Hub.controller"


def test_send_finding_to_team_board_returns_none_for_unlinked_project():
    teams, _backend = _setup()
    task = teams.send_finding_to_team_board(
        "not-a-linked-uuid", "Some finding", source_type="animation"
    )
    assert task is None


def test_task_crud_round_trip():
    teams, _backend = _setup()
    task = teams.create_task("team-1", "Task A", project_uuid=PROJECT_UUID)
    assert teams.list_tasks_for_project(PROJECT_UUID)[0].id == task.id

    updated = teams.update_task("team-1", task.id, status_value="in_progress")
    assert updated.status == "in_progress"

    teams.delete_task("team-1", task.id)
    assert teams.list_tasks_for_project(PROJECT_UUID) == []


def test_comment_round_trip_for_project():
    teams, _backend = _setup()
    comment = teams.add_comment_for_project(PROJECT_UUID, "known_issue", "42", "Regressed again")
    assert comment is not None
    listed = teams.comments_for_project_subject(PROJECT_UUID, "known_issue", "42")
    assert [c.body for c in listed] == ["Regressed again"]


def test_comment_for_unlinked_project_is_noop():
    teams, _backend = _setup()
    assert teams.add_comment_for_project("unlinked", "known_issue", "1", "hi") is None
    assert teams.comments_for_project_subject("unlinked", "known_issue", "1") == []


def test_discipline_self_service_and_my_discipline():
    teams, _backend = _setup()
    teams.set_my_discipline("team-1", "audio")
    assert teams.my_discipline(PROJECT_UUID) == "audio"


def test_relevant_members_for_project_event_uses_routing():
    teams, backend = _setup()
    backend.members.append(
        TeamMember(
            id="m2", team_id="team-1", user_id="u2", invited_email=None, role="member",
            discipline="audio", joined_at="2026-08-04T00:00:00Z", created_at="2026-08-04T00:00:00Z",
        )
    )
    relevant = teams.relevant_members_for_project_event(PROJECT_UUID, "audio_checklist_gap")
    assert [m.user_id for m in relevant] == ["u2"]


def test_relevant_members_for_unlinked_project_is_empty():
    teams, _backend = _setup()
    assert teams.relevant_members_for_project_event("unlinked", "audio_checklist_gap") == []
