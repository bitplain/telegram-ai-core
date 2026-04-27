"""memories and portfolio_assets tables; purge OpenRouter key from app_settings

Revision ID: 0006_memories_portfolio
Revises: 0005_agent_history_idx
Create Date: 2026-04-27 18:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_memories_portfolio"
down_revision: Union[str, None] = "0005_agent_history_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text("DELETE FROM app_settings WHERE key = 'openrouter_api_key'")
    )

    op.create_table(
        "memories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("agent_id", sa.String(64), nullable=True, index=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_memories_user_scope_created",
        "memories",
        ["user_id", "scope", "created_at"],
        unique=False,
    )

    op.create_table(
        "portfolio_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("average_buy_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("network", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_portfolio_user_symbol_network",
        "portfolio_assets",
        ["user_id", "symbol", "network"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_user_symbol_network", table_name="portfolio_assets")
    op.drop_table("portfolio_assets")
    op.drop_index("ix_memories_user_scope_created", table_name="memories")
    op.drop_table("memories")
