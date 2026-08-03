"""Initial schema: users, teams, team_members, team_projects.

Revision ID: 0001
Revises:
Create Date: 2026-08-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "team_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("invited_email", sa.String(length=320), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_member_user"),
    )

    op.create_table(
        "team_projects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("project_uuid", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("team_id", "project_uuid", name="uq_team_project"),
    )
    op.create_index("ix_team_projects_project_uuid", "team_projects", ["project_uuid"])


def downgrade() -> None:
    op.drop_index("ix_team_projects_project_uuid", table_name="team_projects")
    op.drop_table("team_projects")
    op.drop_table("team_members")
    op.drop_table("teams")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
