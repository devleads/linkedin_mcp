"""add profile browser states table

Revision ID: 011_profile_browser_states
Revises: 010_encrypted_linkedin_password
Create Date: 2026-08-09

Stores Playwright storage_state JSON (cookies + localStorage) per profile
in the database, replacing the filesystem-based PROFILE_STORAGE_PATH approach.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "011_profile_browser_states"
down_revision: Union[str, None] = "010_encrypted_linkedin_password"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_browser_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("storage_state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", name="uq_profile_browser_state_profile"),
    )
    op.create_index(
        "ix_profile_browser_states_profile_id",
        "profile_browser_states",
        ["profile_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_profile_browser_states_profile_id", table_name="profile_browser_states")
    op.drop_table("profile_browser_states")
