"""add browser runtime metadata and write action ledger

Revision ID: 012_runtime_action_ledger
Revises: 011_profile_browser_states
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012_runtime_action_ledger"
down_revision: Union[str, None] = "011_profile_browser_states"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "profiles",
        "totp_secret",
        existing_type=sa.String(length=64),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.create_table(
        "profile_browser_runtimes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("runtime_type", sa.String(length=32), nullable=False, server_default="legacy_injected"),
        sa.Column("profile_path_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("migration_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("chrome_version", sa.String(length=64), nullable=True),
        sa.Column("patchright_version", sa.String(length=64), nullable=True),
        sa.Column("initialized_at", sa.DateTime(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "runtime_type IN ('legacy_injected', 'persistent_native')",
            name="ck_profile_browser_runtime_type",
        ),
        sa.CheckConstraint(
            "migration_status IN ('pending', 'validating', 'complete', 'failed')",
            name="ck_profile_browser_migration_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", name="uq_profile_browser_runtime_profile"),
    )
    op.create_table(
        "profile_action_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("target_identity_hash", sa.String(length=64), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="prepared"),
        sa.Column("result_identity", sa.String(length=255), nullable=True),
        sa.Column("sanitized_error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "state IN ('prepared', 'executing', 'succeeded', 'failed', 'unknown')",
            name="ck_profile_action_ledger_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "action_type", "idempotency_key", name="uq_profile_action_idempotency"),
    )
    op.create_index(
        "ix_profile_action_ledger_profile_started",
        "profile_action_ledger",
        ["profile_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_profile_action_ledger_profile_started", table_name="profile_action_ledger")
    op.drop_table("profile_action_ledger")
    op.drop_table("profile_browser_runtimes")
    op.alter_column(
        "profiles",
        "totp_secret",
        existing_type=sa.Text(),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
