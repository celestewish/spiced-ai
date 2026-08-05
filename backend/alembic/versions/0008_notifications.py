"""Notification Center: notifications table + delivery cadence (Phase K, section 9 part 1).

Adds the actual delivery/storage table (``notifications``) that Phase J's
routing-decision layer anticipated, plus a ``delivery`` cadence column on
``notification_preferences`` (realtime/hourly/daily -- see
``app.models.NotificationPreference``'s docstring).

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column(
            "recipient_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("event_kind", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=True),
        sa.Column("subject_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notifications_team_id", "notifications", ["team_id"])
    op.create_index(
        "ix_notifications_recipient_user_id", "notifications", ["recipient_user_id"]
    )

    op.add_column(
        "notification_preferences",
        sa.Column(
            "delivery", sa.String(length=20), nullable=False, server_default="realtime"
        ),
    )


def downgrade() -> None:
    op.drop_column("notification_preferences", "delivery")
    op.drop_index("ix_notifications_recipient_user_id", table_name="notifications")
    op.drop_index("ix_notifications_team_id", table_name="notifications")
    op.drop_table("notifications")
