"""Thin HTTP client for the Spiced backend's team endpoints.

Every call attaches the caller's Supabase JWT as a Bearer token; the backend
verifies it against Supabase Auth on each request (see backend/app/auth.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

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
    # Discipline/skill role (Phase J, Role-Based Dashboards) — see
    # app.models.TeamMember.discipline. Defaults to None for the same
    # backward-compatibility reason as ``email`` above.
    discipline: str | None = None


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


@dataclass(frozen=True)
class ChangelogEntry:
    id: str
    version_or_phase_label: str
    title: str
    body: str
    published_at: str


@dataclass(frozen=True)
class PlayerCrashReport:
    """A crash/error report a real player of the shipped game submitted.

    Fetched read-only by the desktop client (see
    ``core.player_crash_reports.PlayerCrashSyncService``) to feed into Known
    Issues. Submission itself is never done by Spiced's own UI — it's the
    shipped game's own crash handler, per ``docs/player_crash_reporting.md``.
    """

    id: str
    project_uuid: str
    error_type: str
    message: str
    stack_excerpt: str | None
    app_version: str | None
    occurred_at: str
    reported_at: str


@dataclass(frozen=True)
class RoadmapSuggestion:
    id: str
    author_user_id: str
    title: str
    body: str
    created_at: str
    vote_count: int
    voted_by_me: bool


@dataclass(frozen=True)
class TeamTask:
    """Unified Task Board (Phase J) row. ``source_type``/``source_ref``
    trace a task back to the finding that generated it, when created via a
    "Send to Team Board" routing entry point rather than typed by hand."""

    id: str
    team_id: str
    project_uuid: str | None
    title: str
    description: str | None
    status: str
    assigned_discipline: str | None
    source_type: str
    source_ref: str | None
    created_by_user_id: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Comment:
    """Comment Threads on Assets/Builds (Phase J) row."""

    id: str
    team_id: str
    subject_type: str
    subject_id: str
    author_user_id: str
    body: str
    created_at: str


@dataclass(frozen=True)
class EventRoutingRule:
    """One team's saved override of which discipline(s) an event kind
    routes to (Phase J, Relevance-Based Notifications routing layer)."""

    id: str
    team_id: str
    event_kind: str
    discipline: str
    created_at: str


@dataclass(frozen=True)
class TriggerRule:
    """One team's saved Cross-Feature Rules/Trigger Engine rule
    (Market-Viability Roadmap, Phase 4) -- distinct from
    ``EventRoutingRule``, which decides *who* gets notified; this decides
    *what happens* (see ``app.models.TriggerRule``'s docstring on the
    backend, and ``core.rules_engine`` on the desktop side)."""

    id: str
    team_id: str
    event_kind: str
    min_severity: str
    action: str
    action_params_json: str
    enabled: bool
    created_at: str


@dataclass(frozen=True)
class NotificationPreference:
    """One member's explicit per-event-kind opt-in/opt-out override
    (Phase J, Relevance-Based Notifications routing layer)."""

    id: str
    team_id: str
    user_id: str
    event_kind: str
    enabled: bool
    created_at: str
    # Digest cadence (Phase K, section 9 part 1): "realtime" | "hourly" |
    # "daily". Defaults to "realtime" so existing call sites/fakes built
    # before this field existed keep working, same backward-compatibility
    # reason as TeamMember.email/discipline above.
    delivery: str = "realtime"


@dataclass(frozen=True)
class Notification:
    """One delivered notification (Phase K, section 9 part 1, Core tier).

    Mirrors ``Comment``'s subject_type/subject_id shape (both nullable here,
    since not every event kind points at a specific team-scoped row -- see
    ``app.models.Notification``'s docstring on the backend).
    """

    id: str
    team_id: str
    recipient_user_id: str
    event_kind: str
    title: str
    body: str
    subject_type: str | None
    subject_id: str | None
    created_at: str
    read_at: str | None


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

    # --- Open Roadmap & Feedback Loop (Phase C) -----------------------------
    # Viewing the changelog and suggestion board needs no login (``require_auth
    # =False``); submitting a suggestion or voting requires the same
    # Supabase-authenticated account as Team Mode.

    def list_changelog(self) -> list[ChangelogEntry]:
        payload = self._request("GET", "/roadmap/changelog", require_auth=False)
        return [_changelog_entry(row) for row in payload]

    def list_suggestions(self) -> list[RoadmapSuggestion]:
        payload = self._request("GET", "/roadmap/suggestions", require_auth=False)
        return [_suggestion(row) for row in payload]

    def create_suggestion(self, title: str, body: str) -> RoadmapSuggestion:
        payload = self._request(
            "POST", "/roadmap/suggestions", json={"title": title, "body": body}
        )
        return _suggestion(payload)

    def vote_suggestion(self, suggestion_id: str) -> None:
        self._request("POST", f"/roadmap/suggestions/{suggestion_id}/vote")

    def unvote_suggestion(self, suggestion_id: str) -> None:
        self._request("DELETE", f"/roadmap/suggestions/{suggestion_id}/vote")

    # --- Player Crash & Error Reporting (Phase G) ----------------------------
    # Reading requires auth + team membership, same as every other team-
    # visible resource. Submission is never done from this client — it's the
    # shipped game's own crash handler posting directly, with no auth at
    # all (see docs/player_crash_reporting.md); Spiced's desktop app only
    # ever reads reports back.

    def list_player_crashes(self, project_uuid: str) -> list[PlayerCrashReport]:
        payload = self._request("GET", f"/projects/{project_uuid}/player-crashes")
        return [_player_crash(row) for row in payload]

    # --- Role-Based Dashboards: discipline (Phase J) --------------------------

    def set_my_discipline(self, team_id: str, discipline: str | None) -> TeamMember:
        payload = self._request(
            "PATCH", f"/teams/{team_id}/members/me", json={"discipline": discipline}
        )
        return _member(payload)

    def set_member_discipline(
        self, team_id: str, member_id: str, discipline: str | None
    ) -> TeamMember:
        payload = self._request(
            "PATCH", f"/teams/{team_id}/members/{member_id}", json={"discipline": discipline}
        )
        return _member(payload)

    # --- Unified Task Board (Phase J) ------------------------------------------

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
        payload = self._request(
            "POST",
            f"/teams/{team_id}/tasks",
            json={
                "title": title,
                "description": description,
                "project_uuid": project_uuid,
                "assigned_discipline": assigned_discipline,
                "source_type": source_type,
                "source_ref": source_ref,
            },
        )
        return _task(payload)

    def list_tasks(self, team_id: str, project_uuid: str | None = None) -> list[TeamTask]:
        path = f"/teams/{team_id}/tasks"
        if project_uuid:
            path += f"?{urlencode({'project_uuid': project_uuid})}"
        payload = self._request("GET", path)
        return [_task(row) for row in payload]

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
        fields = {
            "title": title,
            "description": description,
            "status": status_value,
            "assigned_discipline": assigned_discipline,
        }
        payload = self._request(
            "PATCH", f"/teams/{team_id}/tasks/{task_id}", json={k: v for k, v in fields.items()}
        )
        return _task(payload)

    def delete_task(self, team_id: str, task_id: str) -> None:
        self._request("DELETE", f"/teams/{team_id}/tasks/{task_id}")

    # --- Comment Threads on Assets/Builds (Phase J) -----------------------------

    def create_comment(
        self, team_id: str, subject_type: str, subject_id: str, body: str
    ) -> Comment:
        payload = self._request(
            "POST",
            f"/teams/{team_id}/comments",
            json={"subject_type": subject_type, "subject_id": subject_id, "body": body},
        )
        return _comment(payload)

    def list_comments(self, team_id: str, subject_type: str, subject_id: str) -> list[Comment]:
        query = urlencode({"subject_type": subject_type, "subject_id": subject_id})
        payload = self._request("GET", f"/teams/{team_id}/comments?{query}")
        return [_comment(row) for row in payload]

    # --- Relevance-Based Notifications: routing layer only (Phase J) -----------
    # No notification is ever delivered/displayed by this client -- see
    # core.notification_routing's module docstring for the Phase K
    # sequencing boundary. These calls only read/write the routing decision
    # data (a team's routing rules, and members' explicit preference
    # overrides) that ``relevant_members_for_event`` consumes.

    def list_routing_rules(self, team_id: str) -> list[EventRoutingRule]:
        payload = self._request("GET", f"/teams/{team_id}/routing-rules")
        return [_routing_rule(row) for row in payload]

    def add_routing_rule(self, team_id: str, event_kind: str, discipline: str) -> EventRoutingRule:
        payload = self._request(
            "POST",
            f"/teams/{team_id}/routing-rules",
            json={"event_kind": event_kind, "discipline": discipline},
        )
        return _routing_rule(payload)

    def delete_routing_rule(self, team_id: str, rule_id: str) -> None:
        self._request("DELETE", f"/teams/{team_id}/routing-rules/{rule_id}")

    # --- Cross-Feature Rules/Trigger Engine (Market-Viability Roadmap,
    # Phase 4) -----------------------------------------------------------
    # Pure CRUD, same shape as the routing-rules calls above -- evaluating a
    # rule against an incoming event (core.rules_engine.evaluate_rules)
    # happens entirely on the desktop side; this client only reads/writes
    # rule configuration.

    def list_trigger_rules(self, team_id: str) -> list[TriggerRule]:
        payload = self._request("GET", f"/teams/{team_id}/trigger-rules")
        return [_trigger_rule(row) for row in payload]

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
        payload = self._request(
            "POST",
            f"/teams/{team_id}/trigger-rules",
            json={
                "event_kind": event_kind,
                "min_severity": min_severity,
                "action": action,
                "action_params_json": action_params_json,
                "enabled": enabled,
            },
        )
        return _trigger_rule(payload)

    def delete_trigger_rule(self, team_id: str, rule_id: str) -> None:
        self._request("DELETE", f"/teams/{team_id}/trigger-rules/{rule_id}")

    def list_notification_preferences(self, team_id: str) -> list[NotificationPreference]:
        payload = self._request("GET", f"/teams/{team_id}/notification-preferences")
        return [_notification_preference(row) for row in payload]

    def set_notification_preference(
        self, team_id: str, event_kind: str, enabled: bool, delivery: str = "realtime"
    ) -> NotificationPreference:
        payload = self._request(
            "PUT",
            f"/teams/{team_id}/notification-preferences/me",
            json={"event_kind": event_kind, "enabled": enabled, "delivery": delivery},
        )
        return _notification_preference(payload)

    # --- Notification Center: the actual inbox (Phase K, section 9 part 1) -

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
        payload = self._request(
            "POST",
            f"/teams/{team_id}/notifications",
            json={
                "recipient_user_id": recipient_user_id,
                "event_kind": event_kind,
                "title": title,
                "body": body,
                "subject_type": subject_type,
                "subject_id": subject_id,
            },
        )
        return _notification(payload)

    def list_notifications(self, team_id: str) -> list[Notification]:
        payload = self._request("GET", f"/teams/{team_id}/notifications")
        return [_notification(row) for row in payload]

    def mark_notification_read(self, team_id: str, notification_id: str) -> Notification:
        payload = self._request(
            "POST", f"/teams/{team_id}/notifications/{notification_id}/read"
        )
        return _notification(payload)

    def _request(self, method: str, path: str, json: dict | None = None, require_auth: bool = True):
        if require_auth and not self._token:
            raise NotAuthenticatedError("Sign in to Spiced Team Mode first.")
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            response = self._http.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
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
        discipline=row.get("discipline"),
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


def _changelog_entry(row: dict) -> ChangelogEntry:
    return ChangelogEntry(
        id=row["id"],
        version_or_phase_label=row["version_or_phase_label"],
        title=row["title"],
        body=row["body"],
        published_at=row["published_at"],
    )


def _player_crash(row: dict) -> PlayerCrashReport:
    return PlayerCrashReport(
        id=row["id"],
        project_uuid=row["project_uuid"],
        error_type=row["error_type"],
        message=row["message"],
        stack_excerpt=row.get("stack_excerpt"),
        app_version=row.get("app_version"),
        occurred_at=row["occurred_at"],
        reported_at=row["reported_at"],
    )


def _suggestion(row: dict) -> RoadmapSuggestion:
    return RoadmapSuggestion(
        id=row["id"],
        author_user_id=row["author_user_id"],
        title=row["title"],
        body=row["body"],
        created_at=row["created_at"],
        vote_count=row["vote_count"],
        voted_by_me=row["voted_by_me"],
    )


def _task(row: dict) -> TeamTask:
    return TeamTask(
        id=row["id"],
        team_id=row["team_id"],
        project_uuid=row.get("project_uuid"),
        title=row["title"],
        description=row.get("description"),
        status=row["status"],
        assigned_discipline=row.get("assigned_discipline"),
        source_type=row["source_type"],
        source_ref=row.get("source_ref"),
        created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _comment(row: dict) -> Comment:
    return Comment(
        id=row["id"],
        team_id=row["team_id"],
        subject_type=row["subject_type"],
        subject_id=row["subject_id"],
        author_user_id=row["author_user_id"],
        body=row["body"],
        created_at=row["created_at"],
    )


def _routing_rule(row: dict) -> EventRoutingRule:
    return EventRoutingRule(
        id=row["id"],
        team_id=row["team_id"],
        event_kind=row["event_kind"],
        discipline=row["discipline"],
        created_at=row["created_at"],
    )


def _trigger_rule(row: dict) -> TriggerRule:
    return TriggerRule(
        id=row["id"],
        team_id=row["team_id"],
        event_kind=row["event_kind"],
        min_severity=row["min_severity"],
        action=row["action"],
        action_params_json=row["action_params_json"],
        enabled=row["enabled"],
        created_at=row["created_at"],
    )


def _notification_preference(row: dict) -> NotificationPreference:
    return NotificationPreference(
        id=row["id"],
        team_id=row["team_id"],
        user_id=row["user_id"],
        event_kind=row["event_kind"],
        enabled=row["enabled"],
        created_at=row["created_at"],
        delivery=row.get("delivery", "realtime"),
    )


def _notification(row: dict) -> Notification:
    return Notification(
        id=row["id"],
        team_id=row["team_id"],
        recipient_user_id=row["recipient_user_id"],
        event_kind=row["event_kind"],
        title=row["title"],
        body=row["body"],
        subject_type=row.get("subject_type"),
        subject_id=row.get("subject_id"),
        created_at=row["created_at"],
        read_at=row.get("read_at"),
    )
