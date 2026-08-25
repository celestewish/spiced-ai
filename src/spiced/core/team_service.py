"""Small-Team Mode use-cases: teams, invites, and project linking.

Thin orchestration over BackendClient plus the local project row: keeps the
caller's JWT in sync with AuthService and mints a project's project_uuid the
first time it's linked to a team.
"""

from __future__ import annotations

from spiced.backend_client.api_client import (
    BackendAPIError,
    BackendClient,
    Comment,
    EventRoutingRule,
    NotAuthenticatedError,
    Notification,
    NotificationPreference,
    PlayerCrashReport,
    Team,
    TeamMember,
    TeamProject,
    TeamSessionSummary,
    TeamTask,
    TriggerRule,
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
        task = self._synced_client().create_task(
            team_id,
            title,
            description=description,
            project_uuid=project_uuid,
            assigned_discipline=assigned_discipline,
            source_type=source_type,
            source_ref=source_ref,
        )
        # Notification Center event source (Phase K, #b): a new team task
        # assigned to a discipline notifies whoever's currently on that
        # discipline for this team. No-op (nothing to route dynamically to)
        # for a task created with no discipline set.
        if assigned_discipline:
            self._notify_task_assigned(team_id, task)
        return task

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
        task = self._synced_client().update_task(
            team_id,
            task_id,
            title=title,
            description=description,
            status_value=status_value,
            assigned_discipline=assigned_discipline,
        )
        # Same notification as create_task above, for reassignment -- only
        # when this call actually set a discipline.
        if assigned_discipline:
            self._notify_task_assigned(team_id, task)
        return task

    def _notify_task_assigned(self, team_id: str, task: TeamTask) -> None:
        author = self._auth.current_user()
        self._notify_event(
            team_id,
            "team_task_assigned",
            f"New task assigned to you: {task.title}",
            (task.description or "").strip() or "You've been assigned a new team task.",
            subject_type="task",
            subject_id=task.id,
            extra_discipline=task.assigned_discipline,
            exclude_user_id=author.id if author else None,
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
        comment = self._synced_client().create_comment(team_id, subject_type, subject_id, body)
        # Notification Center event source (Phase K, #c): a new comment on a
        # team task or known issue notifies whoever's involved with it.
        self._notify_comment(team_id, comment)
        return comment

    def _notify_comment(self, team_id: str, comment: Comment) -> None:
        extra_discipline: str | None = None
        if comment.subject_type == "task":
            task = next(
                (t for t in self.list_tasks(team_id) if t.id == comment.subject_id), None
            )
            extra_discipline = task.assigned_discipline if task else None
        elif comment.subject_type == "known_issue":
            # Matches known_issue_opened/known_issue_regression's own
            # default routing (see core.notification_routing) -- Known
            # Issues are a programmer-facing panel today.
            extra_discipline = "programmer"
        author = self._auth.current_user()
        self._notify_event(
            team_id,
            "comment_posted",
            f"New comment on {comment.subject_type} {comment.subject_id}",
            comment.body,
            subject_type=comment.subject_type,
            subject_id=comment.subject_id,
            extra_discipline=extra_discipline,
            exclude_user_id=author.id if author else None,
        )

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

    # --- Cross-Feature Rules/Trigger Engine (Market-Viability Roadmap,
    # Phase 4) -----------------------------------------------------------
    # Rule *configuration* only, same thin pass-through shape as the
    # routing-rules calls above -- core.rules_engine.evaluate_rules is what
    # actually reads these and decides what to do.

    def list_trigger_rules(self, team_id: str) -> list[TriggerRule]:
        return self._synced_client().list_trigger_rules(team_id)

    def add_trigger_rule(
        self,
        team_id: str,
        event_kind: str,
        min_severity: str,
        action: str,
        *,
        action_params_json: str = "{}",
        enabled: bool = True,
    ) -> TriggerRule:
        return self._synced_client().add_trigger_rule(
            team_id,
            event_kind,
            min_severity,
            action,
            action_params_json=action_params_json,
            enabled=enabled,
        )

    def delete_trigger_rule(self, team_id: str, rule_id: str) -> None:
        self._synced_client().delete_trigger_rule(team_id, rule_id)

    def list_notification_preferences(self, team_id: str) -> list[NotificationPreference]:
        return self._synced_client().list_notification_preferences(team_id)

    def set_notification_preference(
        self, team_id: str, event_kind: str, enabled: bool, delivery: str = "realtime"
    ) -> NotificationPreference:
        return self._synced_client().set_notification_preference(
            team_id, event_kind, enabled, delivery
        )

    def relevant_members_for_project_event(
        self, project_uuid: str, event_kind: str, *, extra_discipline: str | None = None
    ) -> list[TeamMember]:
        """Thin composition wrapper around ``core.notification_routing.
        relevant_members_for_event``: fetches the team's members/routing
        rules/preferences and applies the routing decision. Returns [] for a
        solo/unlinked project. This only answers "who is relevant" -- see
        ``_notify_event``/``notify_relevant_members_for_project_event``
        below for the delivery layer built on top of it."""
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

    # --- Notification Center: the actual delivery/storage layer (Phase K,
    # section 9 part 1) -----------------------------------------------------
    #
    # Everything above this point was Phase J's routing *decision* only.
    # These methods are what actually creates a ``Notification`` row per
    # relevant recipient -- called by the four wired event sources: build
    # failures (``ui.build_scheduler``), team task assignment (above),
    # comments (above), and player crash reports
    # (``core.player_crash_reports.PlayerCrashSyncService``).

    def create_notification(
        self,
        team_id: str,
        recipient_user_id: str,
        event_kind: str,
        title: str,
        body: str,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> Notification:
        return self._synced_client().create_notification(
            team_id,
            recipient_user_id,
            event_kind,
            title,
            body,
            subject_type=subject_type,
            subject_id=subject_id,
        )

    def list_notifications(self, team_id: str) -> list[Notification]:
        """The signed-in user's own notifications for this team, most
        recent first -- fed into ``ui.notification_center``'s digest
        bucketing (``core.notification_center.bucket_by_cadence``)."""
        return self._synced_client().list_notifications(team_id)

    def mark_notification_read(self, team_id: str, notification_id: str) -> Notification:
        return self._synced_client().mark_notification_read(team_id, notification_id)

    def _notify_event(
        self,
        team_id: str,
        event_kind: str,
        title: str,
        body: str,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        extra_discipline: str | None = None,
        exclude_user_id: str | None = None,
    ) -> list[Notification]:
        """Best-effort fan-out: compute who's relevant to ``event_kind`` on
        this team (``core.notification_routing.relevant_members_for_event``,
        fed by this team's saved routing rules/preferences) and create one
        ``Notification`` row per relevant, already-joined member --
        ``exclude_user_id`` is typically the signed-in user themselves, so
        acting on your own task/comment doesn't notify you about it.

        Swallows backend/auth errors so a notification-delivery hiccup never
        blocks the primary action (a task being created, a comment being
        posted, ...) that triggered it -- the same "surface calmly, never
        break the caller" pattern as ``sync_session_summary``/
        ``player_crash_sync`` elsewhere in this app.
        """
        try:
            members = relevant_members_for_event(
                self.list_members(team_id),
                event_kind,
                team_rules=self.list_routing_rules(team_id),
                preferences=self.list_notification_preferences(team_id),
                extra_discipline=extra_discipline,
            )
            created = []
            for member in members:
                if not member.user_id or member.user_id == exclude_user_id:
                    continue
                created.append(
                    self.create_notification(
                        team_id,
                        member.user_id,
                        event_kind,
                        title,
                        body,
                        subject_type=subject_type,
                        subject_id=subject_id,
                    )
                )
            return created
        except (BackendAPIError, NotAuthenticatedError):
            return []

    def notify_relevant_members_for_project_event(
        self,
        project_uuid: str,
        event_kind: str,
        title: str,
        body: str,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        extra_discipline: str | None = None,
        exclude_user_id: str | None = None,
    ) -> list[Notification]:
        """Project-scoped convenience wrapper around ``_notify_event`` for
        event sources that only know a ``project_uuid`` (build failures,
        player crash reports) rather than a ``team_id`` directly. Returns []
        (creates nothing) for a solo/unlinked project or on any backend/auth
        failure -- same best-effort guarantee as ``_notify_event``."""
        try:
            team = self.find_team_for_project(project_uuid)
        except (BackendAPIError, NotAuthenticatedError):
            return []
        if team is None:
            return []
        return self._notify_event(
            team.id,
            event_kind,
            title,
            body,
            subject_type=subject_type,
            subject_id=subject_id,
            extra_discipline=extra_discipline,
            exclude_user_id=exclude_user_id,
        )
