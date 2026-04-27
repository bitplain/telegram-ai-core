"""agent modes and message routing metadata

Revision ID: 0004_agent_modes
Revises: 0003_user_agent_settings
Create Date: 2026-04-27 12:46:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_agent_modes"
down_revision: Union[str, None] = "0003_user_agent_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "active_mode",
            sa.String(length=32),
            nullable=False,
            server_default="default",
        ),
    )
    op.add_column("messages", sa.Column("agent_id", sa.String(length=64), nullable=True))
    op.add_column("messages", sa.Column("skill_id", sa.String(length=64), nullable=True))
    op.add_column("messages", sa.Column("model_id", sa.String(length=64), nullable=True))
    op.create_index("ix_messages_agent_id", "messages", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_agent_id", table_name="messages")
    op.drop_column("messages", "model_id")
    op.drop_column("messages", "skill_id")
    op.drop_column("messages", "agent_id")
    op.drop_column("conversations", "active_mode")
