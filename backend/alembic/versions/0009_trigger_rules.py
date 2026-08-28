"""Cross-Feature Rules/Trigger Engine: trigger_rules table (Market-Viability
Roadmap, Phase 4).

Distinct from ``event_routing_rules``: that table decides who gets
notified about an event kind; this table decides what automated action (if
any) happens -- see ``app.models.TriggerRule``'s docstring.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trigger_rules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("event_kind", sa.String(length=100), nullable=False),
        sa.Column("min_severity", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("action_params_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trigger_rules_team_id", "trigger_rules", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_trigger_rules_team_id", table_name="trigger_rules")
    op.drop_table("trigger_rules")
