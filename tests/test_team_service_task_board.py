"""TeamService tests for the Phase J Unified Task Board / Comment Threads /
discipline / notification-routing wiring, over a fake BackendClient (same
style as test_team_service.py)."""

from __future__ import annotations

from spiced.backend_client.api_client import (
    Comment,
    EventRoutingRule,
    Notification,
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
        self.notifications: list[Notification] = []
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

    def set_notification_preference(self, team_id, event_kind, enabled, delivery="realtime"):
        pref = NotificationPreference(
            id=f"p{len(self.preferences) + 1}", team_id=team_id, user_id="u1",
            event_kind=event_kind, enabled=enabled, created_at="2026-08-04T00:00:00Z",
            delivery=delivery,
        )
        self.preferences.append(pref)
        return pref

    def create_notification(self, team_id, recipient_user_id, event_kind, title, body,
                             *, subject_type=None, subject_id=None):
        notification = Notification(
            id=f"n{len(self.notifications) + 1}", team_id=team_id,
            recipient_user_id=recipient_user_id, event_kind=event_kind, title=title,
            body=body, subject_type=subject_type, subject_id=subject_id,
            created_at="2026-08-04T00:00:00Z", read_at=None,
        )
        self.notifications.append(notification)
        return notification

    def list_notifications(self, team_id):
        return [n for n in self.notifications if n.team_id == team_id]

    def mark_notification_read(self, team_id, notification_id):
        for i, n in enumerate(self.notifications):
            if n.id == notification_id and n.team_id == team_id:
                updated = Notification(
                    id=n.id, team_id=n.team_id, recipient_user_id=n.recipient_user_id,
                    event_kind=n.event_kind, title=n.title, body=n.body,
                    subject_type=n.subject_type, subject_id=n.subject_id,
                    created_at=n.created_at, read_at="2026-08-04T01:00:00Z",
                )
                self.notifications[i] = updated
                return updated
        raise KeyError(notification_id)


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


# --- Notification Center: event sources wired through TeamService (Phase K) -


def test_creating_a_task_with_a_discipline_notifies_the_relevant_member():
    teams, backend = _setup()
    backend.members.append(
        TeamMember(
            id="m2", team_id="team-1", user_id="u2", invited_email=None, role="member",
            discipline="audio", joined_at="2026-08-04T00:00:00Z", created_at="2026-08-04T00:00:00Z",
        )
    )
    task = teams.create_task(
        "team-1", "Mix the boss fight", project_uuid=PROJECT_UUID, assigned_discipline="audio"
    )
    assert len(backend.notifications) == 1
    notification = backend.notifications[0]
    assert notification.recipient_user_id == "u2"
    assert notification.event_kind == "team_task_assigned"
    assert notification.subject_type == "task"
    assert notification.subject_id == task.id


def test_creating_a_task_with_no_discipline_notifies_nobody():
    teams, backend = _setup()
    teams.create_task("team-1", "Untriaged", project_uuid=PROJECT_UUID)
    assert backend.notifications == []


def test_task_assignment_never_notifies_its_own_author():
    """The signed-in user is 'u1' (see _setup) -- assigning a task to their
    own discipline shouldn't notify themselves about their own action."""
    teams, backend = _setup()
    teams.create_task(
        "team-1", "Self-assigned", project_uuid=PROJECT_UUID, assigned_discipline="animation"
    )
    assert backend.notifications == []


def test_reassigning_a_task_on_update_also_notifies():
    teams, backend = _setup()
    backend.members.append(
        TeamMember(
            id="m2", team_id="team-1", user_id="u2", invited_email=None, role="member",
            discipline="audio", joined_at="2026-08-04T00:00:00Z", created_at="2026-08-04T00:00:00Z",
        )
    )
    task = teams.create_task("team-1", "Task A", project_uuid=PROJECT_UUID)
    assert backend.notifications == []
    teams.update_task("team-1", task.id, assigned_discipline="audio")
    assert len(backend.notifications) == 1
    assert backend.notifications[0].recipient_user_id == "u2"


def test_comment_on_a_task_notifies_the_tasks_assigned_discipline():
    teams, backend = _setup()
    backend.members.append(
        TeamMember(
            id="m2", team_id="team-1", user_id="u2", invited_email=None, role="member",
            discipline="audio", joined_at="2026-08-04T00:00:00Z", created_at="2026-08-04T00:00:00Z",
        )
    )
    task = teams.create_task(
        "team-1", "Task A", project_uuid=PROJECT_UUID, assigned_discipline="audio"
    )
    backend.notifications = []  # clear the assignment notification for a clean check below

    teams.add_comment_for_project(PROJECT_UUID, "task", task.id, "Any update?")
    assert len(backend.notifications) == 1
    notification = backend.notifications[0]
    assert notification.recipient_user_id == "u2"
    assert notification.event_kind == "comment_posted"
    assert notification.subject_type == "task"
    assert notification.subject_id == task.id


def test_comment_on_a_known_issue_notifies_programmers():
    teams, backend = _setup()
    backend.members.append(
        TeamMember(
            id="m2", team_id="team-1", user_id="u2", invited_email=None, role="member",
            discipline="programmer", joined_at="2026-08-04T00:00:00Z",
            created_at="2026-08-04T00:00:00Z",
        )
    )
    teams.add_comment_for_project(PROJECT_UUID, "known_issue", "42", "Regressed again")
    assert len(backend.notifications) == 1
    assert backend.notifications[0].recipient_user_id == "u2"


def test_notify_relevant_members_for_project_event_creates_notifications():
    teams, backend = _setup()
    backend.members.append(
        TeamMember(
            id="m2", team_id="team-1", user_id="u2", invited_email=None, role="member",
            discipline="programmer", joined_at="2026-08-04T00:00:00Z",
            created_at="2026-08-04T00:00:00Z",
        )
    )
    created = teams.notify_relevant_members_for_project_event(
        PROJECT_UUID, "build_failed", "Scheduled build failed: Demo", "boom: NRE",
        subject_type="build", subject_id="1",
    )
    assert len(created) == 1
    assert created[0].recipient_user_id == "u2"
    assert backend.notifications == created


def test_notify_relevant_members_for_unlinked_project_creates_nothing():
    teams, backend = _setup()
    created = teams.notify_relevant_members_for_project_event(
        "unlinked", "build_failed", "title", "body"
    )
    assert created == []
    assert backend.notifications == []


def test_notify_relevant_members_excludes_members_with_no_user_id():
    teams, backend = _setup()
    backend.members.append(
        TeamMember(
            id="m2", team_id="team-1", user_id=None, invited_email="pending@example.com",
            role="member", discipline="programmer", joined_at=None,
            created_at="2026-08-04T00:00:00Z",
        )
    )
    created = teams.notify_relevant_members_for_project_event(
        PROJECT_UUID, "build_failed", "title", "body"
    )
    assert created == []
