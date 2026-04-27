"""user ETH balance, digest flags, eth_price_alerts

Revision ID: 0006_eth_digest_alerts
Revises: 0005_agent_history_idx
Create Date: 2026-04-27 18:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_eth_digest_alerts"
down_revision: Union[str, None] = "0005_agent_history_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "eth_balance",
            sa.Numeric(36, 18),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
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
    op.create_table(
        "eth_price_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("target_price_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_eth_price_alerts_user_active",
        "eth_price_alerts",
        ["user_id", "is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_eth_price_alerts_telegram_user_id"),
        "eth_price_alerts",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_eth_price_alerts_user_id"),
        "eth_price_alerts",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_eth_price_alerts_user_id"), table_name="eth_price_alerts")
    op.drop_index(
        op.f("ix_eth_price_alerts_telegram_user_id"), table_name="eth_price_alerts"
    )
    op.drop_index("ix_eth_price_alerts_user_active", table_name="eth_price_alerts")
    op.drop_table("eth_price_alerts")
    op.drop_column("users", "last_digest_sent_at")
    op.drop_column("users", "digest_enabled")
    op.drop_column("users", "eth_balance")
