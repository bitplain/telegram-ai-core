"""Тесты расчёта PnL и форматирования портфеля."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.bot.handlers.portfolio import _format_portfolio_html
from app.core.portfolio.add_eth import parse_add_eth_args
from app.core.portfolio.formatting import format_eth
from app.core.portfolio.pnl import compute_portfolio_pnl
from app.core.portfolio.digest import build_crypto_digest_text
from app.core.portfolio.price_provider import EthMarketSnapshot


def test_pnl_full_position() -> None:
    pnl = compute_portfolio_pnl(
        total_eth=Decimal("2"),
        cost_basis_total_usd=4000.0,
        current_price_usd=2500.0,
    )
    assert not pnl.pnl_data_incomplete
    assert pnl.average_buy_price_usd == 2000.0
    assert pnl.current_value_usd == 5000.0
    assert pnl.unrealized_pnl_usd == pytest.approx(1000.0)
    assert pnl.unrealized_pnl_percent == pytest.approx(25.0)


def test_pnl_without_cost_basis() -> None:
    pnl = compute_portfolio_pnl(
        total_eth=Decimal("1"),
        cost_basis_total_usd=None,
        current_price_usd=3000.0,
    )
    assert pnl.pnl_data_incomplete
    assert pnl.unrealized_pnl_usd is None


def test_pnl_zero_eth() -> None:
    pnl = compute_portfolio_pnl(
        total_eth=Decimal("0"),
        cost_basis_total_usd=100.0,
        current_price_usd=3000.0,
    )
    assert pnl.pnl_data_incomplete


def test_format_portfolio_html_with_price() -> None:
    pnl = compute_portfolio_pnl(
        total_eth=Decimal("1"),
        cost_basis_total_usd=2000.0,
        current_price_usd=3000.0,
    )
    html = _format_portfolio_html(pnl, price_error=None, market_price_usd=3000.0)
    assert "ETH" in html
    assert "Нереал" in html
    assert "3" in html


def test_format_portfolio_html_no_market() -> None:
    pnl = compute_portfolio_pnl(
        total_eth=Decimal("1"),
        cost_basis_total_usd=2000.0,
        current_price_usd=1.0,
    )
    html = _format_portfolio_html(
        pnl, price_error="цена недоступна", market_price_usd=None
    )
    assert "недоступ" in html.lower() or "недостаточно" in html.lower()


def test_parse_add_eth() -> None:
    a, e = parse_add_eth_args("0.1 2000")
    assert e is None
    assert a is not None
    assert a.amount == Decimal("0.1")
    assert a.price_usd_per_eth == 2000.0
    a2, e2 = parse_add_eth_args("0.1")
    assert a2 is not None and e2 is None
    assert a2.price_usd_per_eth is None


def test_crypto_digest_stub_news() -> None:
    m = EthMarketSnapshot(
        price_usd=1000.0, price_rub=90000.0, change_24h_percent=2.5
    )
    pnl = compute_portfolio_pnl(
        total_eth=Decimal("0.5"),
        cost_basis_total_usd=None,
        current_price_usd=1000.0,
    )
    text = build_crypto_digest_text(market=m, pnl=pnl)
    assert "не подключ" in text.lower() or "источник" in text.lower()
    assert "ETH" in text
    assert format_eth(Decimal("0.5")) in text
