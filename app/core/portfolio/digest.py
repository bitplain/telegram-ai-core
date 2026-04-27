"""Текст дневного крипто-дайджеста (без выдуманных новостей)."""

from __future__ import annotations

from app.core.portfolio.formatting import format_eth, format_rub, format_usd
from app.core.portfolio.pnl import PortfolioPnlSnapshot
from app.core.portfolio.price_provider import EthMarketSnapshot
from app.core.news.provider import get_news_provider


def _eth_l2_tips() -> list[str]:
    """Общие осторожные пункты, не выдаваемые за новостную сводку."""
    return [
        "ETH: волатильность выше, чем у большинства классических активов — размер позиции осознанно.",
        "L2: перед первым вводом в новый бридж/кошелёк перепроверяй сеть (chain id) и адреса.",
        "Gas и время блока: в пике сети стоимость и задержки растут — критично для мелких переводов.",
        "DeFi-протоколы: смарт-контрактный риск, неаудитированные пулы и фишинг контрактов в списке угроз.",
    ]


def build_crypto_digest_text(
    *,
    market: EthMarketSnapshot,
    pnl: PortfolioPnlSnapshot | None,
) -> str:
    lines: list[str] = ["<b>Крипто-дайджест (ETH)</b>", ""]

    ch = market.change_24h_percent
    ch_line = f"24h: {ch:+.2f} % к USD" if ch is not None else "24h: нет данных"
    rub_line = (
        f"≈ {format_rub(market.price_rub)}" if market.price_rub is not None else "RUB: нет данных"
    )

    lines.append(f"ETH ≈ {format_usd(market.price_usd)} | {rub_line}")
    lines.append(ch_line)
    lines.append("")

    lines.append("<b>Портфель (учёт в боте)</b>")
    if pnl is not None:
        lines.append(f"Баланс: {format_eth(pnl.total_eth)} ETH")
        if pnl.pnl_data_incomplete and pnl.total_eth > 0:
            lines.append("PnL: " + pnl.pnl_status_message)
        elif pnl.pnl_data_incomplete:
            lines.append("Позиция пуста — /portfolio_add_eth 0.1 2000")
        else:
            lines.append(f"Стоимость: {format_usd(pnl.current_value_usd)}")
            assert pnl.unrealized_pnl_usd is not None
            from app.core.portfolio.formatting import format_percent

            lines.append(
                f"Нереал. PnL: {format_usd(pnl.unrealized_pnl_usd)} "
                f"({format_percent(pnl.unrealized_pnl_percent or 0.0)})"
            )
    else:
        lines.append("Нет данных — /portfolio")

    lines.append("")
    prov = get_news_provider()
    lines.append("<b>Новости</b>")
    if not prov.sources_connected:
        lines.append("Источники новостей в боте не подключены — заголовки не подтягиваем.")
    else:
        lines.append("См. выдачу провайдера.")

    lines.append("")
    lines.append("<b>На заметку (это не сводка рынка)</b>")
    for i, tip in enumerate(_eth_l2_tips()[:5], start=1):
        lines.append(f"{i}. {tip}")

    lines.append("")
    lines.append(
        "Риски: нет гарантий доходности, это не инвестиционная рекомендация. "
        "Автотрейдинг и скан DeFi в боте не ведутся."
    )
    return "\n".join(lines)
