"""ETH position merge math."""

from __future__ import annotations

from decimal import Decimal

from app.db.repositories.portfolio_assets import merge_eth_position


def test_merge_eth_first_add() -> None:
    amt, avg = merge_eth_position(
        old_amount=Decimal("1"),
        old_avg=Decimal("3000"),
        add_amount=Decimal("1"),
        add_price=Decimal("4000"),
    )
    assert amt == Decimal("2")
    assert avg == Decimal("3500")


def test_merge_eth_from_zero() -> None:
    amt, avg = merge_eth_position(
        old_amount=Decimal("0"),
        old_avg=Decimal("0"),
        add_amount=Decimal("0.25"),
        add_price=Decimal("3200"),
    )
    assert amt == Decimal("0.25")
    assert avg == Decimal("3200")
