"""add profile challenge events table

Revision ID: 004_profile_challenge_events
Revises: b9d1eea63dd0
Create Date: 2026-03-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "004_profile_challenge_events"
down_revision: Union[str, None] = "b9d1eea63dd0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_challenge_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("source_tool", sa.String(length=64), nullable=False),
        sa.Column("signal", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_profile_challenge_events_profile_detected",
        "profile_challenge_events",
        ["profile_id", "detected_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_profile_challenge_events_profile_detected", table_name="profile_challenge_events")
    op.drop_table("profile_challenge_events")
