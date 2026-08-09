"""Initial schema - profiles, fingerprints, cookies

Revision ID: 001
Revises: 
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create profiles table
    op.create_table(
        'profiles',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('uuid', sa.String(36), nullable=False),
        sa.Column('linkedin_email', sa.String(255), nullable=False),
        sa.Column('linkedin_password', sa.Text(), nullable=False),
        sa.Column('country', sa.String(10), nullable=False),
        sa.Column('timezone', sa.String(50), nullable=False),
        sa.Column('totp_secret', sa.String(64), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_profiles_uuid', 'profiles', ['uuid'], unique=True)
    
    # Create profile_fingerprints table
    op.create_table(
        'profile_fingerprints',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('user_agent', sa.Text(), nullable=False),
        sa.Column('platform', sa.String(50), nullable=False),
        sa.Column('screen_width', sa.Integer(), nullable=False, default=1920),
        sa.Column('screen_height', sa.Integer(), nullable=False, default=1080),
        sa.Column('color_depth', sa.Integer(), nullable=False, default=24),
        sa.Column('hardware_concurrency', sa.Integer(), nullable=False, default=8),
        sa.Column('device_memory', sa.Integer(), nullable=False, default=8),
        sa.Column('languages', sa.JSON(), nullable=False, default=['en-US', 'en']),
        sa.Column('webgl_vendor', sa.String(255), nullable=False, default='Google Inc.'),
        sa.Column('webgl_renderer', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('profile_id'),
    )
    
    # Create profile_cookies table
    op.create_table(
        'profile_cookies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('domain', sa.String(255), nullable=False, default='.linkedin.com'),
        sa.Column('path', sa.String(255), nullable=False, default='/'),
        sa.Column('secure', sa.Boolean(), nullable=False, default=True),
        sa.Column('http_only', sa.Boolean(), nullable=False, default=True),
        sa.Column('same_site', sa.String(20), nullable=False, default='None'),
        sa.Column('expires', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('profile_id', 'name', name='uq_profile_cookie_name'),
    )
    op.create_index('ix_profile_cookies_profile_id', 'profile_cookies', ['profile_id'])


def downgrade() -> None:
    op.drop_table('profile_cookies')
    op.drop_table('profile_fingerprints')
    op.drop_index('ix_profiles_uuid', 'profiles')
    op.drop_table('profiles')
