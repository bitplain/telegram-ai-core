"""user_agent_settings table

Revision ID: 0003_user_agent_settings
Revises: 0002_app_settings
Create Date: 2026-04-27 13:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_user_agent_settings"
down_revision: Union[str, None] = "0002_app_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_agent_settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("custom_prompt", sa.Text(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "telegram_user_id",
            "agent_id",
            name="uq_user_agent_settings_user_agent",
        ),
    )
    op.create_index(
        "ix_user_agent_settings_telegram_user_id",
        "user_agent_settings",
        ["telegram_user_id"],
    )
    op.create_index(
        "ix_user_agent_settings_agent_id",
        "user_agent_settings",
        ["agent_id"],
    )
    op.create_index(
        "ix_user_agent_settings_model_id",
        "user_agent_settings",
        ["model_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_agent_settings_model_id", table_name="user_agent_settings")
    op.drop_index("ix_user_agent_settings_agent_id", table_name="user_agent_settings")
    op.drop_index(
        "ix_user_agent_settings_telegram_user_id",
        table_name="user_agent_settings",
    )
    op.drop_table("user_agent_settings")
