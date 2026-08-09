"""add profile proxy configs table

Revision ID: 008_profile_proxy_configs
Revises: 007_ipfoxy_profile_fields
Create Date: 2026-04-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "008_profile_proxy_configs"
down_revision: Union[str, None] = "007_ipfoxy_profile_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_proxy_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("password", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "provider", name="uq_profile_proxy_provider"),
    )
    op.create_index(
        "ix_profile_proxy_configs_profile_provider",
        "profile_proxy_configs",
        ["profile_id", "provider"],
        unique=False,
    )

    # Backfill existing dedicated IPFoxy fields into extensible table
    op.execute(
        """
        INSERT INTO profile_proxy_configs (
            profile_id, provider, host, port, username, password, is_active
        )
        SELECT
            id, 'ipfoxy', ipfoxy_host, ipfoxy_port, ipfoxy_username, ipfoxy_password, true
        FROM profiles
        WHERE ipfoxy_host IS NOT NULL
          OR ipfoxy_port IS NOT NULL
          OR ipfoxy_username IS NOT NULL
          OR ipfoxy_password IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_profile_proxy_configs_profile_provider", table_name="profile_proxy_configs")
    op.drop_table("profile_proxy_configs")
