"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-27 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
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
        sa.UniqueConstraint("telegram_user_id", name="uq_users_telegram_user_id"),
    )
    op.create_index(
        "ix_users_telegram_user_id", "users", ["telegram_user_id"], unique=False
    )

    op.create_table(
        "chats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("telegram_chat_id", name="uq_chats_telegram_chat_id"),
    )
    op.create_index(
        "ix_chats_telegram_chat_id", "chats", ["telegram_chat_id"], unique=False
    )

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="ACTIVE"
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "active_agent_id",
            sa.String(length=64),
            nullable=False,
            server_default="general",
        ),
        sa.Column(
            "active_skill_id",
            sa.String(length=64),
            nullable=False,
            server_default="chat",
        ),
        sa.Column(
            "active_model_id",
            sa.String(length=64),
            nullable=False,
            server_default="default_balanced",
        ),
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
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_conversations_user_id"
        ),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], ondelete="CASCADE", name="fk_conversations_chat_id"
        ),
        sa.UniqueConstraint(
            "user_id",
            "chat_id",
            "status",
            name="uq_conversation_user_chat_status",
        ),
    )
    op.create_index(
        "ix_conversations_user_id", "conversations", ["user_id"], unique=False
    )
    op.create_index(
        "ix_conversations_chat_id", "conversations", ["chat_id"], unique=False
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("raw_update_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
            name="fk_messages_conversation_id",
        ),
    )
    op.create_index(
        "ix_messages_conversation_id", "messages", ["conversation_id"], unique=False
    )
    op.create_index(
        "ix_messages_conv_created_at",
        "messages",
        ["conversation_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "llm_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "agent_id", sa.String(length=64), nullable=False, server_default="general"
        ),
        sa.Column(
            "skill_id", sa.String(length=64), nullable=False, server_default="chat"
        ),
        sa.Column(
            "model_id",
            sa.String(length=64),
            nullable=False,
            server_default="default_balanced",
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_model_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
            name="fk_llm_requests_conversation_id",
        ),
    )
    op.create_index(
        "ix_llm_requests_conversation_id",
        "llm_requests",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_llm_requests_conv_created_at",
        "llm_requests",
        ["conversation_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "processed_updates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_update_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "telegram_update_id", name="uq_processed_updates_telegram_update_id"
        ),
    )
    op.create_index(
        "ix_processed_updates_telegram_update_id",
        "processed_updates",
        ["telegram_update_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_processed_updates_telegram_update_id", table_name="processed_updates"
    )
    op.drop_table("processed_updates")

    op.drop_index("ix_llm_requests_conv_created_at", table_name="llm_requests")
    op.drop_index("ix_llm_requests_conversation_id", table_name="llm_requests")
    op.drop_table("llm_requests")

    op.drop_index("ix_messages_conv_created_at", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_conversations_chat_id", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index("ix_chats_telegram_chat_id", table_name="chats")
    op.drop_table("chats")

    op.drop_index("ix_users_telegram_user_id", table_name="users")
    op.drop_table("users")
