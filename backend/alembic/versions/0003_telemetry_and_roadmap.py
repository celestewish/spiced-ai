"""Telemetry events, plus the Roadmap's changelog/suggestions/votes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("anonymous_client_id", sa.String(length=36), nullable=False),
        sa.Column("event_name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_telemetry_events_anonymous_client_id",
        "telemetry_events",
        ["anonymous_client_id"],
    )

    op.create_table(
        "changelog_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("version_or_phase_label", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "roadmap_suggestions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "author_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "roadmap_votes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "suggestion_id",
            sa.String(length=36),
            sa.ForeignKey("roadmap_suggestions.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("suggestion_id", "user_id", name="uq_roadmap_vote"),
    )
    op.create_index("ix_roadmap_votes_suggestion_id", "roadmap_votes", ["suggestion_id"])


def downgrade() -> None:
    op.drop_index("ix_roadmap_votes_suggestion_id", table_name="roadmap_votes")
    op.drop_table("roadmap_votes")
    op.drop_table("roadmap_suggestions")
    op.drop_table("changelog_entries")
    op.drop_index("ix_telemetry_events_anonymous_client_id", table_name="telemetry_events")
    op.drop_table("telemetry_events")
