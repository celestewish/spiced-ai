"""Small-Team Mode use-cases: teams, invites, and project linking.

Thin orchestration over BackendClient plus the local project row: keeps the
caller's JWT in sync with AuthService and mints a project's project_uuid the
first time it's linked to a team.
"""

from __future__ import annotations

from spiced.backend_client.api_client import (
    BackendClient,
    Comment,
    EventRoutingRule,
    NotificationPreference,
    PlayerCrashReport,
    Team,
    TeamMember,
    TeamProject,
    TeamSessionSummary,
    TeamTask,
)
from spiced.core.auth_service import AuthService
from spiced.core.notification_routing import relevant_members_for_event
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

    # --- Role-Based Dashboards: discipline (Phase J) --------------------------

    def set_my_discipline(self, team_id: str, discipline: str | None) -> TeamMember:
        return self._synced_client().set_my_discipline(team_id, discipline)

    def set_member_discipline(
        self, team_id: str, member_id: str, discipline: str | None
    ) -> TeamMember:
        return self._synced_client().set_member_discipline(team_id, member_id, discipline)

    def my_discipline(self, project_uuid: str) -> str | None:
        """The signed-in user's discipline on the team ``project_uuid`` is
        linked to, if any -- feeds the Context Panel's role-based summary
        section (#4). Returns None for a solo/unlinked project, a signed-out
        user, or a member with no discipline set."""
        team = self.find_team_for_project(project_uuid)
        if team is None:
            return None
        user = self._auth.current_user()
        if user is None:
            return None
        member = next((m for m in self.list_members(team.id) if m.user_id == user.id), None)
        return member.discipline if member else None

    # --- Unified Task Board (Phase J) -----------------------------------------

    def create_task(
        self,
        team_id: str,
        title: str,
        *,
        description: str | None = None,
        project_uuid: str | None = None,
        assigned_discipline: str | None = None,
        source_type: str = "manual",
        source_ref: str | None = None,
    ) -> TeamTask:
        return self._synced_client().create_task(
            team_id,
            title,
            description=description,
            project_uuid=project_uuid,
            assigned_discipline=assigned_discipline,
            source_type=source_type,
            source_ref=source_ref,
        )

    def list_tasks(self, team_id: str, project_uuid: str | None = None) -> list[TeamTask]:
        return self._synced_client().list_tasks(team_id, project_uuid=project_uuid)

    def list_tasks_for_project(self, project_uuid: str) -> list[TeamTask]:
        """Convenience: resolve the team for a project then list its tasks.
        Returns [] for a project that isn't team-linked -- the Team screen's
        Kanban board is only visible/usable for team-linked projects."""
        team = self.find_team_for_project(project_uuid)
        if team is None:
            return []
        return self.list_tasks(team.id, project_uuid=project_uuid)

    def update_task(
        self,
        team_id: str,
        task_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        status_value: str | None = None,
        assigned_discipline: str | None = None,
    ) -> TeamTask:
        return self._synced_client().update_task(
            team_id,
            task_id,
            title=title,
            description=description,
            status_value=status_value,
            assigned_discipline=assigned_discipline,
        )

    def delete_task(self, team_id: str, task_id: str) -> None:
        self._synced_client().delete_task(team_id, task_id)

    def send_finding_to_team_board(
        self,
        project_uuid: str,
        title: str,
        *,
        description: str | None = None,
        assigned_discipline: str | None = None,
        source_type: str,
        source_ref: str | None = None,
    ) -> TeamTask | None:
        """Create a ``TeamTask`` pre-filled from an existing feature's
        finding, if this project is team-linked. Returns None (creates
        nothing) otherwise -- the concrete "route automatically to the
        relevant role" entry point spec'd for feedback clusters/bugs, wired
        into the Animation Bug Detection, Audio Implementation Checklist,
        and Known Issues panels' "Send to Team Board" actions (see those
        screens)."""
        team = self.find_team_for_project(project_uuid)
        if team is None:
            return None
        return self.create_task(
            team.id,
            title,
            description=description,
            project_uuid=project_uuid,
            assigned_discipline=assigned_discipline,
            source_type=source_type,
            source_ref=source_ref,
        )

    # --- Comment Threads on Assets/Builds (Phase J) ---------------------------

    def create_comment(
        self, team_id: str, subject_type: str, subject_id: str, body: str
    ) -> Comment:
        return self._synced_client().create_comment(team_id, subject_type, subject_id, body)

    def list_comments(self, team_id: str, subject_type: str, subject_id: str) -> list[Comment]:
        return self._synced_client().list_comments(team_id, subject_type, subject_id)

    def comments_for_project_subject(
        self, project_uuid: str, subject_type: str, subject_id: str
    ) -> list[Comment]:
        """Resolve the team for a project then list comments on one
        subject. Returns [] for a project that isn't team-linked -- comments
        require a team_id and are only shown/usable for team-linked
        projects."""
        team = self.find_team_for_project(project_uuid)
        if team is None:
            return []
        return self.list_comments(team.id, subject_type, subject_id)

    def add_comment_for_project(
        self, project_uuid: str, subject_type: str, subject_id: str, body: str
    ) -> Comment | None:
        team = self.find_team_for_project(project_uuid)
        if team is None:
            return None
        return self.create_comment(team.id, subject_type, subject_id, body)

    # --- Relevance-Based Notifications: routing layer only (Phase J) ----------
    # No notification is ever delivered/displayed here -- see
    # core.notification_routing's module docstring for the Phase K
    # sequencing boundary this deliberately stops short of.

    def list_routing_rules(self, team_id: str) -> list[EventRoutingRule]:
        return self._synced_client().list_routing_rules(team_id)

    def add_routing_rule(self, team_id: str, event_kind: str, discipline: str) -> EventRoutingRule:
        return self._synced_client().add_routing_rule(team_id, event_kind, discipline)

    def delete_routing_rule(self, team_id: str, rule_id: str) -> None:
        self._synced_client().delete_routing_rule(team_id, rule_id)

    def list_notification_preferences(self, team_id: str) -> list[NotificationPreference]:
        return self._synced_client().list_notification_preferences(team_id)

    def set_notification_preference(
        self, team_id: str, event_kind: str, enabled: bool
    ) -> NotificationPreference:
        return self._synced_client().set_notification_preference(team_id, event_kind, enabled)

    def relevant_members_for_project_event(
        self, project_uuid: str, event_kind: str, *, extra_discipline: str | None = None
    ) -> list[TeamMember]:
        """Thin composition wrapper around ``core.notification_routing.
        relevant_members_for_event``: fetches the team's members/routing
        rules/preferences and applies the routing decision. Returns [] for a
        solo/unlinked project. This never delivers anything -- it only
        answers "who is relevant," for Phase K's future Notification Center
        to eventually call."""
        team = self.find_team_for_project(project_uuid)
        if team is None:
            return []
        members = self.list_members(team.id)
        rules = self.list_routing_rules(team.id)
        preferences = self.list_notification_preferences(team.id)
        return relevant_members_for_event(
            members,
            event_kind,
            team_rules=rules,
            preferences=preferences,
            extra_discipline=extra_discipline,
        )
