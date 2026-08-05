"""Comment Threads on Assets/Builds: comments (Phase J, section 8 part 2).

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("team_id", sa.String(length=36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=False),
        sa.Column(
            "author_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_comments_team_id", "comments", ["team_id"])
    op.create_index("ix_comments_subject_id", "comments", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_comments_subject_id", table_name="comments")
    op.drop_index("ix_comments_team_id", table_name="comments")
    op.drop_table("comments")
