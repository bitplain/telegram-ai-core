"""Команды /portfolio, /portfolio_add_eth, /crypto_digest."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.handlers.commands import _ensure_conversation
from app.bot.renderers.telegram_text import escape_html, send_long_html, send_plain
from app.core.portfolio.add_eth import parse_add_eth_args
from app.core.portfolio.digest import build_crypto_digest_text
from app.core.portfolio.formatting import format_eth, format_percent, format_usd
from app.core.portfolio.pnl import compute_portfolio_pnl, PortfolioPnlSnapshot
from app.core.portfolio.price_provider import get_eth_market_snapshot
from app.db.repositories.users import UserRepository
from app.db.session import session_scope

router = Router(name="portfolio")

PORTFOLIO_ADD_HELP = (
    "Формат: <code>/portfolio_add_eth &lt;кол-во&gt; [цена_USD/ETH]</code>\n"
    "Пример с ценой: <code>/portfolio_add_eth 0.5 2500</code>\n"
    "Без цены (только баланс): <code>/portfolio_add_eth 0.1</code>"
)


def _format_portfolio_html(
    pnl: PortfolioPnlSnapshot,
    *,
    price_error: str | None,
    market_price_usd: float | None,
) -> str:
    lines: list[str] = ["<b>ETH портфель (учёт в боте)</b>", ""]
    if price_error:
        lines.append(escape_html(price_error))
        lines.append("")

    lines.append(f"Всего: <b>{format_eth(pnl.total_eth)}</b> ETH")

    if pnl.total_eth == 0:
        lines.append(PORTFOLIO_ADD_HELP)
        lines.append("")
        lines.append(escape_html("Это не инвестиционная рекомендация. Крипто-активы рискованы."))
        return "\n".join(lines)

    if pnl.pnl_data_incomplete or pnl.average_buy_price_usd is None:
        lines.append("Средняя закупка: <i>недостаточно данных</i>")
    else:
        lines.append(
            f"Средняя закупка: {format_usd(pnl.average_buy_price_usd)}/ETH"
        )

    if market_price_usd is None:
        lines.append("Цена сейчас: <i>недоступна</i>")
        lines.append("Оценка стоимости и PnL: <i>недостаточно данных</i> (нет актуальной цены)")
    else:
        lines.append(f"Цена сейчас: {format_usd(market_price_usd)}/ETH")
        lines.append(f"Оценка стоимости: {format_usd(pnl.current_value_usd)}")

        if pnl.pnl_data_incomplete:
            lines.append("PnL: <i>недостаточно данных</i> — укажи цену в /portfolio_add_eth")
        else:
            assert pnl.unrealized_pnl_usd is not None
            lines.append(
                f"Нереал. PnL: {format_usd(pnl.unrealized_pnl_usd)} "
                f"({format_percent(pnl.unrealized_pnl_percent or 0.0)})"
            )
    lines.append("")
    lines.append(
        escape_html(
            "Оценка ориентировочная. Не автотрейдинг. Не инвестиционная рекомендация."
        )
    )
    return "\n".join(lines)


@router.message(Command("portfolio"))
async def cmd_portfolio(message: Message) -> None:
    if message.from_user is None or message.chat is None:
        return
    await _ensure_conversation(message)
    tid = message.from_user.id
    async with session_scope() as session:
        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(tid)
        if user is None:
            await send_long_html(message.bot, message.chat.id, "Сначала /start.")
            return
        amount = user.eth_balance
        basis = user.eth_cost_basis_usd

    snap, price_err = await get_eth_market_snapshot()
    if snap is not None:
        pnl = compute_portfolio_pnl(
            total_eth=amount,
            cost_basis_total_usd=basis,
            current_price_usd=snap.price_usd,
        )
        text = _format_portfolio_html(
            pnl, price_error=None, market_price_usd=snap.price_usd
        )
    else:
        pnl = compute_portfolio_pnl(
            total_eth=amount,
            cost_basis_total_usd=basis,
            current_price_usd=1.0,
        )
        text = _format_portfolio_html(
            pnl, price_error=price_err, market_price_usd=None
        )

    await send_long_html(message.bot, message.chat.id, text)


@router.message(Command("portfolio_add_eth"))
async def cmd_portfolio_add_eth(message: Message, command: CommandObject) -> None:
    if message.from_user is None or message.chat is None:
        return
    await _ensure_conversation(message)
    parsed, err = parse_add_eth_args(command.args or "")
    if err:
        await send_long_html(
            message.bot,
            message.chat.id,
            f"{escape_html(err)}\n\n{PORTFOLIO_ADD_HELP}",
        )
        return
    if parsed is None:
        await send_long_html(
            message.bot, message.chat.id, PORTFOLIO_ADD_HELP
        )
        return

    tid = message.from_user.id
    try:
        async with session_scope() as session:
            repo = UserRepository(session)
            user = await repo.get_by_telegram_id(tid)
            if user is None:
                await send_long_html(message.bot, message.chat.id, "Сначала /start.")
                return
            await repo.add_eth_purchase(
                telegram_user_id=tid,
                amount=parsed.amount,
                price_usd_per_eth=parsed.price_usd_per_eth,
            )
    except ValueError as exc:
        if str(exc) == "user_not_found":
            await send_long_html(message.bot, message.chat.id, "Сначала /start.")
            return
        raise

    price_note = "" if parsed.price_usd_per_eth is not None else " (для PnL позже укажи цену)"
    await send_plain(
        message.bot,
        message.chat.id,
        f"Добавлено {format_eth(parsed.amount)} ETH{price_note}. /portfolio",
    )


@router.message(Command("crypto_digest"))
async def cmd_crypto_digest(message: Message) -> None:
    if message.from_user is None or message.chat is None:
        return
    await _ensure_conversation(message)
    tid = message.from_user.id

    snap, m_err = await get_eth_market_snapshot()
    if snap is None:
        await send_long_html(
            message.bot,
            message.chat.id,
            escape_html(m_err or "Котировки недоступны."),
        )
        return

    pnl: PortfolioPnlSnapshot | None
    async with session_scope() as session:
        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(tid)
        if user is None:
            pnl = None
        else:
            pnl = compute_portfolio_pnl(
                total_eth=user.eth_balance,
                cost_basis_total_usd=user.eth_cost_basis_usd,
                current_price_usd=snap.price_usd,
            )

    text = build_crypto_digest_text(market=snap, pnl=pnl)
    await send_long_html(message.bot, message.chat.id, text)


__all__ = ["router"]
