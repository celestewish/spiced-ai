"""Role-Based Dashboards + Relevance-Based Notifications (Phase J).

Adds ``team_members.discipline`` and the two routing-decision tables
(``event_routing_rules``, ``notification_preferences``) -- no delivery/inbox
table, since that's Phase K's job (see ``app.routers.notifications``'s
docstring).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("team_members", sa.Column("discipline", sa.String(length=50), nullable=True))

    op.create_table(
        "event_routing_rules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("event_kind", sa.String(length=100), nullable=False),
        sa.Column("discipline", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "team_id", "event_kind", "discipline", name="uq_event_routing_rule"
        ),
    )
    op.create_index("ix_event_routing_rules_team_id", "event_routing_rules", ["team_id"])

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_kind", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "team_id", "user_id", "event_kind", name="uq_notification_pref"
        ),
    )
    op.create_index(
        "ix_notification_preferences_team_id", "notification_preferences", ["team_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_preferences_team_id", table_name="notification_preferences"
    )
    op.drop_table("notification_preferences")
    op.drop_index("ix_event_routing_rules_team_id", table_name="event_routing_rules")
    op.drop_table("event_routing_rules")
    op.drop_column("team_members", "discipline")
