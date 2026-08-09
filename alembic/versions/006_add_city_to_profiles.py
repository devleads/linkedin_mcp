"""add city column to profiles

Revision ID: 006_add_city_to_profiles
Revises: 005_add_state_to_profiles
Create Date: 2026-04-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "006_add_city_to_profiles"
down_revision: Union[str, None] = "005_add_state_to_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("city", sa.String(length=96), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "city")
