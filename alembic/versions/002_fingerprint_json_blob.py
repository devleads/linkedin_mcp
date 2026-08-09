"""Refactor fingerprint to single JSON blob

Revision ID: 002
Revises: 001
Create Date: 2024-01-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new fingerprint_data column
    op.add_column('profile_fingerprints', sa.Column('fingerprint_data', sa.JSON(), nullable=True))
    
    # Migrate existing data to JSON blob
    op.execute("""
        UPDATE profile_fingerprints SET fingerprint_data = jsonb_build_object(
            'user_agent', user_agent,
            'platform', platform,
            'screen_width', screen_width,
            'screen_height', screen_height,
            'color_depth', color_depth,
            'hardware_concurrency', hardware_concurrency,
            'device_memory', device_memory,
            'languages', languages,
            'webgl_vendor', webgl_vendor,
            'webgl_renderer', webgl_renderer
        )
    """)
    
    # Make fingerprint_data not nullable
    op.alter_column('profile_fingerprints', 'fingerprint_data', nullable=False)
    
    # Drop old columns
    op.drop_column('profile_fingerprints', 'user_agent')
    op.drop_column('profile_fingerprints', 'platform')
    op.drop_column('profile_fingerprints', 'screen_width')
    op.drop_column('profile_fingerprints', 'screen_height')
    op.drop_column('profile_fingerprints', 'color_depth')
    op.drop_column('profile_fingerprints', 'hardware_concurrency')
    op.drop_column('profile_fingerprints', 'device_memory')
    op.drop_column('profile_fingerprints', 'languages')
    op.drop_column('profile_fingerprints', 'webgl_vendor')
    op.drop_column('profile_fingerprints', 'webgl_renderer')


def downgrade() -> None:
    # Add back old columns
    op.add_column('profile_fingerprints', sa.Column('user_agent', sa.Text(), nullable=True))
    op.add_column('profile_fingerprints', sa.Column('platform', sa.String(50), nullable=True))
    op.add_column('profile_fingerprints', sa.Column('screen_width', sa.Integer(), nullable=True))
    op.add_column('profile_fingerprints', sa.Column('screen_height', sa.Integer(), nullable=True))
    op.add_column('profile_fingerprints', sa.Column('color_depth', sa.Integer(), nullable=True))
    op.add_column('profile_fingerprints', sa.Column('hardware_concurrency', sa.Integer(), nullable=True))
    op.add_column('profile_fingerprints', sa.Column('device_memory', sa.Integer(), nullable=True))
    op.add_column('profile_fingerprints', sa.Column('languages', sa.JSON(), nullable=True))
    op.add_column('profile_fingerprints', sa.Column('webgl_vendor', sa.String(255), nullable=True))
    op.add_column('profile_fingerprints', sa.Column('webgl_renderer', sa.Text(), nullable=True))
    
    # Migrate data back
    op.execute("""
        UPDATE profile_fingerprints SET
            user_agent = fingerprint_data->>'user_agent',
            platform = fingerprint_data->>'platform',
            screen_width = (fingerprint_data->>'screen_width')::integer,
            screen_height = (fingerprint_data->>'screen_height')::integer,
            color_depth = (fingerprint_data->>'color_depth')::integer,
            hardware_concurrency = (fingerprint_data->>'hardware_concurrency')::integer,
            device_memory = (fingerprint_data->>'device_memory')::integer,
            languages = fingerprint_data->'languages',
            webgl_vendor = fingerprint_data->>'webgl_vendor',
            webgl_renderer = fingerprint_data->>'webgl_renderer'
    """)
    
    # Make columns not nullable
    op.alter_column('profile_fingerprints', 'user_agent', nullable=False)
    op.alter_column('profile_fingerprints', 'platform', nullable=False)
    op.alter_column('profile_fingerprints', 'screen_width', nullable=False)
    op.alter_column('profile_fingerprints', 'screen_height', nullable=False)
    op.alter_column('profile_fingerprints', 'color_depth', nullable=False)
    op.alter_column('profile_fingerprints', 'hardware_concurrency', nullable=False)
    op.alter_column('profile_fingerprints', 'device_memory', nullable=False)
    op.alter_column('profile_fingerprints', 'languages', nullable=False)
    op.alter_column('profile_fingerprints', 'webgl_vendor', nullable=False)
    op.alter_column('profile_fingerprints', 'webgl_renderer', nullable=False)
    
    # Drop fingerprint_data column
    op.drop_column('profile_fingerprints', 'fingerprint_data')
