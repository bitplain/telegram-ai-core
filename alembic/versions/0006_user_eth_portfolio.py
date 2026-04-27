"""user ETH portfolio: balance and USD cost basis

Revision ID: 0006_eth_portfolio
Revises: 0005_agent_history_idx
Create Date: 2026-04-27 16:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_eth_portfolio"
down_revision: Union[str, None] = "0005_agent_history_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "eth_balance",
            sa.Numeric(38, 18),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("eth_cost_basis_usd", postgresql.DOUBLE_PRECISION(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "eth_cost_basis_usd")
    op.drop_column("users", "eth_balance")
