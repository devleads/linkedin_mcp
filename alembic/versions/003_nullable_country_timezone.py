"""Make country and timezone nullable

Revision ID: 003
Revises: 002
Create Date: 2024-01-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make country nullable (null = no proxy)
    op.alter_column('profiles', 'country',
                    existing_type=sa.String(10),
                    nullable=True)
    
    # Make timezone nullable
    op.alter_column('profiles', 'timezone',
                    existing_type=sa.String(50),
                    nullable=True)


def downgrade() -> None:
    # Set default values for null entries before making non-nullable
    op.execute("UPDATE profiles SET country = 'US' WHERE country IS NULL")
    op.execute("UPDATE profiles SET timezone = 'UTC' WHERE timezone IS NULL")
    
    op.alter_column('profiles', 'country',
                    existing_type=sa.String(10),
                    nullable=False)
    
    op.alter_column('profiles', 'timezone',
                    existing_type=sa.String(50),
                    nullable=False)
