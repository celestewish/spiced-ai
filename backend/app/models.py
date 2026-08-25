"""SQLAlchemy models for auth, teams, and team-linked projects.

IDs are stored as 36-char UUID strings rather than a Postgres-native UUID
column so the same models work unchanged against SQLite in tests and Postgres
in production.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    """Mirrors a Supabase auth.users row. Created lazily on first verified request."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Subscription(Base):
    """Billing Foundation (Market-Viability Roadmap, Phase 5): one Stripe
    subscription, mirrored locally so plan-gating never has to call Stripe
    on every request.

    ``user_id`` is never nullable -- a Stripe customer is always a specific
    person's payment method, even when the plan is meant to cover a team's
    shared usage. ``team_id`` is the optional "this plan covers this team"
    tag on top of that, not a second, mutually-exclusive owner axis; a
    purely individual subscription simply leaves it unset. Rows are
    upserted by ``stripe_subscription_id`` from the webhook handler
    (``routers.billing.handle_webhook``) as Stripe's own source of truth
    changes -- this table is a mirror, never written to independently of a
    real Stripe event (except the temporary ``status="incomplete"`` row a
    checkout session creation may pre-create, see that endpoint).

    ``status`` stores Stripe's own subscription status string verbatim
    (``active``, ``trialing``, ``past_due``, ``canceled``, ...) rather than
    a narrower app-invented enum, so this table never falls out of sync
    with what Stripe itself considers valid.
    """

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    team_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("teams.id"), nullable=True, index=True
    )
    plan_key: Mapped[str] = mapped_column(String(20))
    stripe_customer_id: Mapped[str] = mapped_column(String(255), index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(30))
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    members: Mapped[list[TeamMember]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    projects: Mapped[list[TeamProject]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


# Role-Based Permissions (Market-Viability Roadmap, Phase 6). A small,
# explicit 3-tier set -- resisted the urge to design a fuller permissions
# matrix beyond the report's actual cited need ("control who sees budget/
# contract data vs. own role's task board"). ROLE_RANK backs
# routers.teams.require_role's "at least this senior" check.
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
VALID_ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_MEMBER)
ROLE_RANK = {ROLE_MEMBER: 0, ROLE_ADMIN: 1, ROLE_OWNER: 2}


class TeamMember(Base):
    """A team membership row.

    Invites by email work without an email-sending service: when a team owner
    invites someone who has never signed in, ``user_id`` is left null and
    ``invited_email`` records the address. The next time any user
    authenticates (see ``app.auth.get_current_user``), pending rows matching
    their verified email are attached to their user id and marked joined.

    ``role`` (Phase 6): ``owner`` (the team creator, exactly one per team,
    never assignable via invite), ``admin``, or ``member`` -- see
    ``routers.teams.require_role``, the dependency that makes this
    load-bearing rather than the vestigial field it was before Phase 6.
    """

    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"))
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    invited_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    # Discipline/skill role (Phase J, section 8 part 2 -- Role-Based
    # Dashboards + Relevance-Based Notifications routing). Deliberately NOT
    # the same field as ``role`` above, which is membership-only
    # ("owner"/"member"). A free-ish string with a small suggested set
    # (programmer/artist/audio/animation/design) rather than a rigid enum,
    # since indie teams don't fit neat boxes -- see docs on the desktop
    # Settings/Team screens for the suggested values shown in the UI.
    # Settable via self-service (PATCH .../members/me) or by any team member
    # (PATCH .../members/{member_id}), mirroring the existing permissiveness
    # of invite_member (no owner-only gate exists anywhere in this router).
    discipline: Mapped[str | None] = mapped_column(String(50), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    team: Mapped[Team] = relationship(back_populates="members")
    user: Mapped[User | None] = relationship()

    @property
    def email(self) -> str | None:
        """Best-available contact address: the invite address while pending,
        otherwise the joined user's verified email.

        ``invited_email`` is cleared once a membership resolves to a real
        user (see ``routers.teams.invite_member``), so this falls back to
        the related ``User`` row — used by Team Mode prompt context (Phase B)
        to show teammates by name/email rather than a bare user id.
        """
        return self.invited_email or (self.user.email if self.user else None)


class AuditLogEntry(Base):
    """One recorded team-scoped mutation (Market-Viability Roadmap, Phase
    6). Additive only -- see ``app.audit.record_audit_event``, which is
    called from the same database session as the mutation it's logging
    (added to the session before that endpoint's own ``db.commit()``, not
    committed separately), so an audit row and the change it describes are
    always persisted atomically together, never one without the other.

    ``action`` is a short, stable verb-noun string (e.g.
    ``"member.invited"``, ``"member.removed"``, ``"team.created"``) rather
    than a free-text description -- keeps this table filterable/groupable
    without parsing prose. ``target_type``/``target_id`` mirror ``Comment``/
    ``Notification``'s existing subject_type/subject_id shape;
    ``metadata_json`` carries the few action-specific extras worth keeping
    (e.g. the invited email, the role that changed) as a JSON blob, same
    reasoning as ``TriggerRule.action_params_json``.

    Landing incrementally per-router (this phase wires ``routers.teams``'
    seven mutating endpoints; other team-scoped routers are real, named
    follow-up -- see the roadmap document) rather than a single big-bang
    sweep, per the roadmap's own explicit scope note for this table.
    """

    __tablename__ = "audit_log_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), index=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TeamProject(Base):
    """Links a client-minted ``project_uuid`` (a local Spiced project) to a team."""

    __tablename__ = "team_projects"
    __table_args__ = (UniqueConstraint("team_id", "project_uuid", name="uq_team_project"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"))
    project_uuid: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    team: Mapped[Team] = relationship(back_populates="projects")


class SessionSummary(Base):
    """A dev-session recap posted from a team-linked project (Phase B).

    Only the AI-produced summary text and start/end timestamps are stored
    here — never raw session timing framed as a wellbeing signal (how late
    or how long someone worked). That data is Crunch-Pattern Awareness
    material, which stays local-only by design (see the Phase B/F plan);
    this table only ever receives what the desktop client explicitly opts
    to share once a project is team-linked.
    """

    __tablename__ = "session_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), index=True)
    project_uuid: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TelemetryEvent(Base):
    """Opt-In Only Telemetry (Phase C, section 5).

    No auth, and deliberately no ``user_id``/``team_id`` column at all —
    telemetry is anonymous by design, not tied to a team or account, even if
    the sender happens to be signed in elsewhere. ``anonymous_client_id`` is
    a random UUID the desktop client mints once and stores locally (see
    ``spiced.app.services.Services.record_telemetry_event``); it identifies a
    machine, never a person. ``event_name`` is a bare event name (e.g.
    "debugging.crash_diagnosis_run") — the schema has no field for code,
    logs, file paths, feedback content, or any project/game content, so none
    of that can be sent here even by mistake.
    """

    __tablename__ = "telemetry_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    anonymous_client_id: Mapped[str] = mapped_column(String(36), index=True)
    event_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PlayerCrashReport(Base):
    """A crash/error report submitted by an end player of a shipped game
    (Phase G, section 7 — Player Crash & Error Reporting).

    No auth on ingestion: players don't have Spiced accounts. Only accepted
    for a ``project_uuid`` that's linked to a team (see ``TeamProject`` and
    ``routers.player_crashes``) — solo/local-only projects never mint a
    ``project_uuid`` at all, so there is nothing to report against; this is
    consistent with Spiced's local-first design, not an arbitrary
    restriction. Field lengths mirror the caps enforced in the router
    (``message``/``stack_excerpt`` are never accepted unbounded).
    """

    __tablename__ = "player_crash_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_uuid: Mapped[str] = mapped_column(String(36), index=True)
    error_type: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(String(2000))
    stack_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ChangelogEntry(Base):
    """Spiced's own public release notes (Open Roadmap, Phase C, stretch).

    Distinct from ``core/changelog_draft.py`` planned for Phase D, which
    drafts patch notes for the *developer's own game* — this table is
    Spiced's release history, shown to every user on the Roadmap screen.
    """

    __tablename__ = "changelog_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version_or_phase_label: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RoadmapSuggestion(Base):
    """A developer-submitted roadmap suggestion. Requires a signed-in author."""

    __tablename__ = "roadmap_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    author_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RoadmapVote(Base):
    """One user's upvote on one suggestion. Unique per (suggestion, user)."""

    __tablename__ = "roadmap_votes"
    __table_args__ = (
        UniqueConstraint("suggestion_id", "user_id", name="uq_roadmap_vote"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    suggestion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roadmap_suggestions.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TeamTask(Base):
    """Unified Task Board (Phase J, section 8 part 2, Core tier).

    A single flat task list per team, optionally scoped to one team-linked
    project (``project_uuid`` nullable — a team could in principle track a
    cross-project task, though the desktop UI only ever creates project-
    scoped ones today). ``source_type``/``source_ref`` trace a task back to
    whatever finding generated it (e.g. an Animation Bug Detection result, a
    Known Issue signature) when it was created via one of the "Send to Team
    Board" routing entry points rather than typed in by hand.
    """

    __tablename__ = "team_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), index=True)
    project_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    # e.g. "programmer"/"artist"/"audio"/"animation"/"design"/None -- same
    # free-ish vocabulary as TeamMember.discipline, not enforced as a foreign
    # key against it (a task can be pre-filled with a discipline no current
    # member has claimed yet).
    assigned_discipline: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 'manual' | 'feedback' | 'bug' | 'animation' | 'audio' | 'known_issue' | ...
    source_type: Mapped[str] = mapped_column(String(30), default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Comment(Base):
    """Comment Threads on Assets/Builds (Phase J, section 8 part 2, Phase 2 tier).

    ``subject_type`` is a small fixed set matching what actually exists to
    comment on today ('task' | 'known_issue' | 'build' | 'session_summary');
    ``subject_id`` is a string (not a foreign key) since those subjects live
    in different tables/shapes -- a ``TeamTask.id`` (uuid string) and a local
    Known Issue id (a SQLite integer, stringified) don't share a type. Only
    ever created for a team-linked subject; comments have no meaning for a
    solo/local-only project.
    """

    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[str] = mapped_column(String(100), index=True)
    author_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EventRoutingRule(Base):
    """Relevance-Based Notifications: a team's own routing rule (Phase J).

    Overrides ``core.notification_routing.DEFAULT_EVENT_KIND_DISCIPLINES``
    for one ``event_kind`` on one team: if a team has at least one saved
    rule for a given event kind, those rule rows replace the hardcoded
    default for that team (see ``notification_routing.disciplines_for_event``)
    rather than merging with it, so a team can narrow or widen the default
    set without fighting it. Purely a routing *decision* input -- see
    ``EventRoutingRule``/``NotificationPreference``'s shared module docstring
    note (Phase K sequencing) in ``core.notification_routing``: nothing here
    delivers or displays a notification.
    """

    __tablename__ = "event_routing_rules"
    __table_args__ = (
        UniqueConstraint("team_id", "event_kind", "discipline", name="uq_event_routing_rule"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), index=True)
    event_kind: Mapped[str] = mapped_column(String(100))
    discipline: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TriggerRule(Base):
    """Cross-Feature Rules/Trigger Engine: one team's saved automation rule
    (Market-Viability Roadmap, Phase 4).

    Distinct from ``EventRoutingRule`` above: that table decides *who* gets
    notified about an event kind. This table decides *what happens* --
    ``core.rules_engine.evaluate_rules`` loads a team's rows for an incoming
    ``event_kind`` and, for each whose ``min_severity`` the event's own
    severity meets or exceeds, runs ``action`` (one of the fixed small set
    in ``core.rules_engine`` -- deliberately not a scripting DSL, see that
    module's docstring). ``action_params_json`` carries the few
    action-specific extras a rule needs (e.g. ``create_task``'s
    ``assigned_discipline``) -- kept as a JSON blob rather than dedicated
    columns since it varies per action and this table doesn't need to query
    on it.

    No ``discipline`` column here (unlike ``EventRoutingRule``): the
    ``notify`` action reuses ``EventRoutingRule``'s own routing data
    directly rather than duplicating a second discipline mapping.
    """

    __tablename__ = "trigger_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), index=True)
    event_kind: Mapped[str] = mapped_column(String(100))
    min_severity: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(50))
    action_params_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class NotificationPreference(Base):
    """Relevance-Based Notifications: one member's explicit override (Phase J).

    Absence of a row for a (team, user, event_kind) triple means "use the
    discipline-based default" (see ``core.notification_routing``); a row
    here always wins, letting any member opt in or out of an event kind
    regardless of their own discipline. Readable by any team member (routing
    decisions need everyone's overrides to compute who's relevant), but only
    writable by the row's own owner (see ``routers.notifications.
    set_my_notification_preference``, a ``.../me`` endpoint).

    ``delivery`` (Phase K, section 9 part 1 -- Notification Center's digest
    options) is the cadence this member wants this event kind delivered at:
    'realtime' (the default -- surfaced as soon as the desktop client's
    poller sees it), 'hourly', or 'daily'. The backend has no concept of a
    held/batched notification -- every row in ``notifications`` is always
    immediately listable; digest batching is entirely a desktop-side
    decision (see ``core.notification_center.bucket_by_cadence``) keyed off
    this field.
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", "event_kind", name="uq_notification_pref"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    event_kind: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    delivery: Mapped[str] = mapped_column(String(20), default="realtime")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Notification(Base):
    """Notification Center: one delivered notification (Phase K, section 9
    part 1, Core tier).

    The actual delivery/storage layer Phase J's routing decision
    (``core.notification_routing.relevant_members_for_event``) anticipated:
    one row per relevant recipient, created (server-side logic doesn't exist
    yet, so today always by the desktop client) whenever a wired event
    source fires -- see ``core.team_service.TeamService._notify_event`` and
    its callers (task assignment, comments, build failures, player crash
    reports). ``subject_type``/``subject_id`` mirror ``Comment``'s shape
    (see that model's docstring for why ``subject_id`` is a plain string)
    but both are nullable here, since not every event kind has a specific
    subject to point back to (e.g. a build failure points at the project,
    not a team-scoped row with an id in this database).
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), index=True)
    recipient_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    event_kind: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    subject_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
