"""notification outbox for durable Telegram delivery

Revision ID: 0007_notification_outbox
Revises: 0006_eth_digest_alert
Create Date: 2026-04-28 12:05:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_notification_outbox"
down_revision: Union[str, None] = "0006_eth_digest_alert"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_type", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("parse_mode", sa.Text(), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_retries",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            ["user_id"],
            ["users.id"],
            name="fk_notification_outbox_user_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_notification_outbox_status_next_retry",
        "notification_outbox",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_outbox_notification_type",
        "notification_outbox",
        ["notification_type"],
        unique=False,
    )
    op.create_index(
        "ix_notification_outbox_telegram_chat_id",
        "notification_outbox",
        ["telegram_chat_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_outbox_created_at",
        "notification_outbox",
        ["created_at"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_eth_price_alerts_notification_outbox_id",
        "eth_price_alerts",
        "notification_outbox",
        ["notification_outbox_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_eth_price_alerts_notification_outbox_id",
        "eth_price_alerts",
        type_="foreignkey",
    )
    op.drop_index("ix_notification_outbox_created_at", table_name="notification_outbox")
    op.drop_index(
        "ix_notification_outbox_telegram_chat_id", table_name="notification_outbox"
    )
    op.drop_index(
        "ix_notification_outbox_notification_type", table_name="notification_outbox"
    )
    op.drop_index(
        "ix_notification_outbox_status_next_retry", table_name="notification_outbox"
    )
    op.drop_table("notification_outbox")
