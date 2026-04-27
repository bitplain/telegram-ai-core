"""active conversation partial unique index and agent history index

Revision ID: 0005_active_conversation_history_indexes
Revises: 0004_agent_modes
Create Date: 2026-04-27 15:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_active_conversation_history_indexes"
down_revision: Union[str, None] = "0004_agent_modes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_conversation_user_chat_status",
        "conversations",
        type_="unique",
    )
    op.create_index(
        "uq_conversation_active_user_chat",
        "conversations",
        ["user_id", "chat_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_messages_conv_agent_created_at",
        "messages",
        ["conversation_id", "agent_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conv_agent_created_at", table_name="messages")
    op.drop_index("uq_conversation_active_user_chat", table_name="conversations")
    op.create_unique_constraint(
        "uq_conversation_user_chat_status",
        "conversations",
        ["user_id", "chat_id", "status"],
    )
