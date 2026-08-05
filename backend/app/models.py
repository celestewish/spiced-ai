"""SQLAlchemy models for auth, teams, and team-linked projects.

IDs are stored as 36-char UUID strings rather than a Postgres-native UUID
column so the same models work unchanged against SQLite in tests and Postgres
in production.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
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


class TeamMember(Base):
    """A team membership row.

    Invites by email work without an email-sending service: when a team owner
    invites someone who has never signed in, ``user_id`` is left null and
    ``invited_email`` records the address. The next time any user
    authenticates (see ``app.auth.get_current_user``), pending rows matching
    their verified email are attached to their user id and marked joined.
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
