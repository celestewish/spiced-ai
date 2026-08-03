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
