"""store encrypted linkedin password

Revision ID: 010_encrypted_linkedin_password
Revises: 009_drop_ipfoxy_legacy
Create Date: 2026-05-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010_encrypted_linkedin_password"
down_revision: Union[str, None] = "009_drop_ipfoxy_legacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("linkedin_password_encrypted", sa.Text(), nullable=True))
    op.drop_column("profiles", "linkedin_password")


def downgrade() -> None:
    op.add_column("profiles", sa.Column("linkedin_password", sa.Text(), nullable=True))
    op.drop_column("profiles", "linkedin_password_encrypted")
