"""Session summaries, and a contact-email column on team_members.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_summaries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("project_uuid", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_session_summaries_team_id", "session_summaries", ["team_id"])
    op.create_index(
        "ix_session_summaries_project_uuid", "session_summaries", ["project_uuid"]
    )


def downgrade() -> None:
    op.drop_index("ix_session_summaries_project_uuid", table_name="session_summaries")
    op.drop_index("ix_session_summaries_team_id", table_name="session_summaries")
    op.drop_table("session_summaries")
