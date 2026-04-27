"""portfolio_wallets watch-only addresses

Revision ID: 0007_portfolio_wallets
Revises: 0006_memories_portfolio
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision: str = "0007_portfolio_wallets"
down_revision: Union[str, None] = "0006_memories_portfolio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_wallets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("network", sa.String(64), nullable=False),
        sa.Column("address", sa.String(256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_portfolio_wallets_user_network_address",
        "portfolio_wallets",
        ["user_id", "network", "address"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_portfolio_wallets_user_network_address", table_name="portfolio_wallets"
    )
    op.drop_table("portfolio_wallets")
