"""drop legacy ipfoxy columns from profiles

Revision ID: 009_drop_ipfoxy_legacy
Revises: 008_profile_proxy_configs
Create Date: 2026-04-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "009_drop_ipfoxy_legacy"
down_revision: Union[str, None] = "008_profile_proxy_configs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("profiles", "ipfoxy_password")
    op.drop_column("profiles", "ipfoxy_username")
    op.drop_column("profiles", "ipfoxy_port")
    op.drop_column("profiles", "ipfoxy_host")


def downgrade() -> None:
    op.add_column("profiles", sa.Column("ipfoxy_host", sa.String(length=255), nullable=True))
    op.add_column("profiles", sa.Column("ipfoxy_port", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("ipfoxy_username", sa.String(length=255), nullable=True))
    op.add_column("profiles", sa.Column("ipfoxy_password", sa.Text(), nullable=True))

    # Rehydrate legacy columns from extensible table for backward compatibility
    op.execute(
        """
        UPDATE profiles p
        SET
            ipfoxy_host = cfg.host,
            ipfoxy_port = cfg.port,
            ipfoxy_username = cfg.username,
            ipfoxy_password = cfg.password
        FROM profile_proxy_configs cfg
        WHERE cfg.profile_id = p.id
          AND cfg.provider = 'ipfoxy'
          AND cfg.is_active = true
        """
    )
