"""Расчёт нереализованного PnL для позиции ETH (информация, не рекомендация)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PortfolioPnlSnapshot:
    total_eth: Decimal
    average_buy_price_usd: float | None
    current_price_usd: float
    current_value_usd: float
    cost_basis_usd: float | None
    unrealized_pnl_usd: float | None
    unrealized_pnl_percent: float | None
    pnl_data_incomplete: bool
    pnl_status_message: str


def compute_portfolio_pnl(
    *,
    total_eth: Decimal,
    cost_basis_total_usd: float | None,
    current_price_usd: float,
) -> PortfolioPnlSnapshot:
    """Считает PnL по полной себестоимости позиции.

    ``cost_basis_total_usd`` — сумма (кол-во * цена) по всем вводам; средняя =
    cost_basis / amount.
    Если средней нет (нет вводов с ценой) — PnL не показываем.
    """
    amount = total_eth
    if amount < 0:
        amount = Decimal("0")

    current_value = float(amount) * current_price_usd
    basis = cost_basis_total_usd
    avg: float | None
    if basis is not None and float(amount) > 0 and basis > 0:
        avg = basis / float(amount)
    else:
        avg = None

    incomplete = basis is None or float(amount) <= 0 or basis <= 0 or avg is None

    if incomplete:
        return PortfolioPnlSnapshot(
            total_eth=amount,
            average_buy_price_usd=avg,
            current_price_usd=current_price_usd,
            current_value_usd=current_value,
            cost_basis_usd=basis,
            unrealized_pnl_usd=None,
            unrealized_pnl_percent=None,
            pnl_data_incomplete=True,
            pnl_status_message="Недостаточно данных для PnL: укажи покупки с ценой.",
        )

    pnl = current_value - basis
    pnl_pct = (pnl / basis) * 100.0 if basis else None
    return PortfolioPnlSnapshot(
        total_eth=amount,
        average_buy_price_usd=avg,
        current_price_usd=current_price_usd,
        current_value_usd=current_value,
        cost_basis_usd=basis,
        unrealized_pnl_usd=pnl,
        unrealized_pnl_percent=pnl_pct,
        pnl_data_incomplete=False,
        pnl_status_message="",
    )


__all__ = ["PortfolioPnlSnapshot", "compute_portfolio_pnl"]
