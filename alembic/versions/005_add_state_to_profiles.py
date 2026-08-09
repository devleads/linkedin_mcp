"""add state column to profiles

Revision ID: 005_add_state_to_profiles
Revises: 004_profile_challenge_events
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005_add_state_to_profiles"
down_revision: Union[str, None] = "004_profile_challenge_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("state", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "state")
