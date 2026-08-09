"""add ipfoxy proxy fields to profiles

Revision ID: 007_ipfoxy_profile_fields
Revises: 006_add_city_to_profiles
Create Date: 2026-04-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "007_ipfoxy_profile_fields"
down_revision: Union[str, None] = "006_add_city_to_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("ipfoxy_host", sa.String(length=255), nullable=True))
    op.add_column("profiles", sa.Column("ipfoxy_port", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("ipfoxy_username", sa.String(length=255), nullable=True))
    op.add_column("profiles", sa.Column("ipfoxy_password", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "ipfoxy_password")
    op.drop_column("profiles", "ipfoxy_username")
    op.drop_column("profiles", "ipfoxy_port")
    op.drop_column("profiles", "ipfoxy_host")
