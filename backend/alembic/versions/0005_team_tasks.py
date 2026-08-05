"""Unified Task Board: team_tasks (Phase J, section 8 part 2).

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "team_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("project_uuid", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("assigned_discipline", sa.String(length=50), nullable=True),
        sa.Column("source_type", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("source_ref", sa.String(length=300), nullable=True),
        sa.Column(
            "created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_team_tasks_team_id", "team_tasks", ["team_id"])
    op.create_index("ix_team_tasks_project_uuid", "team_tasks", ["project_uuid"])


def downgrade() -> None:
    op.drop_index("ix_team_tasks_project_uuid", table_name="team_tasks")
    op.drop_index("ix_team_tasks_team_id", table_name="team_tasks")
    op.drop_table("team_tasks")
