"""ETH alerts and daily digest user columns

Revision ID: 0006_eth_digest_alert
Revises: 0005_agent_history_idx
Create Date: 2026-04-28 12:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_eth_digest_alert"
down_revision: Union[str, None] = "0005_agent_history_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "digest_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_digest_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("digest_telegram_chat_id", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "eth_price_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("target_price_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_outbox_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            name="fk_eth_price_alerts_user_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_eth_price_alerts_user_id",
        "eth_price_alerts",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_eth_price_alerts_active",
        "eth_price_alerts",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "ix_eth_price_alerts_telegram_chat_id",
        "eth_price_alerts",
        ["telegram_chat_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_eth_price_alerts_telegram_chat_id", table_name="eth_price_alerts")
    op.drop_index("ix_eth_price_alerts_active", table_name="eth_price_alerts")
    op.drop_index("ix_eth_price_alerts_user_id", table_name="eth_price_alerts")
    op.drop_table("eth_price_alerts")
    op.drop_column("users", "digest_telegram_chat_id")
    op.drop_column("users", "digest_enabled")
