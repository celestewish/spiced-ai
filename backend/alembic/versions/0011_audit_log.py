"""Role-Based Permissions + Audit Log: audit_log_entries table
(Market-Viability Roadmap, Phase 6).

No schema change needed for ``TeamMember.role`` itself -- it was already a
free ``String(20)`` column; Phase 6 makes the three values it's now
constrained to (``owner``/``admin``/``member``) load-bearing at the
application layer (``routers.teams.require_role``), not via a new DB
constraint, matching how this codebase validates other constrained-string
fields (e.g. ``Finding.status``/``severity``) in Python rather than SQL.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column(
            "actor_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_entries_team_id", "audit_log_entries", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_entries_team_id", table_name="audit_log_entries")
    op.drop_table("audit_log_entries")
