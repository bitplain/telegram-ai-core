"""Текст ответа по портфелю ETH (только данные из БД и публичного API цены)."""

from __future__ import annotations

import httpx

from app.bot.renderers.telegram_text import escape_html
from app.core.price.eth import fetch_eth_usd_price
from app.db.repositories.users import UserRepository
from app.db.session import AsyncSession
from app.utils.formatting import format_decimal


async def build_portfolio_message_html(
    session: AsyncSession, *, telegram_user_id: int
) -> str:
    user_repo = UserRepository(session)
    user = await user_repo.get_by_telegram_id(telegram_user_id)
    eth = float(user.eth_balance or 0) if user else 0.0
    lines = [
        "<b>Портфель (учёт в боте)</b>",
        "",
        f"ETH: <b>{escape_html(format_decimal(eth))}</b>",
    ]
    async with httpx.AsyncClient(headers={"User-Agent": "TelegramAICore/1.0"}) as client:
        px = await fetch_eth_usd_price(client=client)
    if px is not None:
        usd_val = eth * px
        lines.append(
            f"Ориентировочная цена ETH: <b>${escape_html(format_decimal(px, max_decimals=2))}</b>"
        )
        lines.append(f"Оценка позиции: <b>≈ ${escape_html(format_decimal(usd_val, max_decimals=2))}</b>")
    else:
        lines.append("Цена ETH сейчас недоступна (внешний API).")
    lines.append("")
    lines.append("Добавить ETH: <code>/add_eth 0.5</code>")
    return "\n".join(lines)
