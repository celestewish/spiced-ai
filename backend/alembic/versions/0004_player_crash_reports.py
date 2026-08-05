"""Player crash reports (Phase G, section 7).

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "player_crash_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_uuid", sa.String(length=36), nullable=False),
        sa.Column("error_type", sa.String(length=200), nullable=False),
        sa.Column("message", sa.String(length=2000), nullable=False),
        sa.Column("stack_excerpt", sa.Text(), nullable=True),
        sa.Column("app_version", sa.String(length=100), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_player_crash_reports_project_uuid",
        "player_crash_reports",
        ["project_uuid"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_player_crash_reports_project_uuid", table_name="player_crash_reports"
    )
    op.drop_table("player_crash_reports")
