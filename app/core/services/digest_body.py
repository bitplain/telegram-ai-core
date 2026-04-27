"""Текст ежедневного дайджеста: цена, портфель, краткий LLM-обзор."""

from __future__ import annotations

import logging

from app.bot.handlers.portfolio_helpers import build_portfolio_message_html
from app.core.news.providers.aggregate import fetch_crypto_news
from app.core.services.crypto_context import build_crypto_analyst_context_block
from app.core.settings_store import get_settings_store
from app.db.session import AsyncSession
from app.llm.openrouter_client import OpenRouterClient, get_openrouter_client
from app.models.registry import get_model_registry
from app.utils.formatting import format_decimal

log = logging.getLogger(__name__)


async def build_daily_digest_html(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    client: OpenRouterClient | None = None,
) -> str:
    """HTML-сообщение для отправки пользователю."""
    portfolio_block = await build_portfolio_message_html(
        session, telegram_user_id=telegram_user_id
    )
    context_block = await build_crypto_analyst_context_block(
        session, telegram_user_id=telegram_user_id
    )
    brief = ""
    store = get_settings_store()
    api_key = await store.get_openrouter_api_key()
    own_client = client is None
    or_client = client or get_openrouter_client()
    if api_key:
        model = get_model_registry().get("crypto_model")
        system = (
            "Ты криптоаналитик. Дай очень краткий обзор (5–8 предложений) на русском "
            "по данным контекста. Начни с фразы: «Это не финансовая рекомендация». "
            "Упомяни риски и один альтернативный сценарий. Не выдумывай факты вне контекста."
        )
        user_msg = f"Контекст:\n{context_block}\n\nСформулируй краткий дайджест для пользователя."
        try:
            result = await or_client.chat_completion(
                model=model.model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.35,
                max_tokens=600,
                api_key_override=api_key,
            )
            brief = (result.content or "").strip()
        except Exception:  # noqa: BLE001
            log.exception("digest_llm_failed")
            brief = "Краткий анализ сейчас недоступен (ошибка модели)."
    else:
        brief = "Краткий анализ недоступен: не настроен OpenRouter API key."

    lines = [
        "<b>Ежедневный дайджест</b>",
        "",
        portfolio_block,
        "",
        "<b>Краткий обзор</b>",
        "",
        brief,
    ]
    return "\n".join(lines)


async def build_digest_for_tests(*, include_llm: bool = False) -> str:
    """Упрощённая сборка для unit-тестов без БД (только новости + заглушка портфеля)."""
    import httpx

    async with httpx.AsyncClient(headers={"User-Agent": "TelegramAICore-test/1.0"}) as hc:
        items, err = await fetch_crypto_news(client=hc, min_items=1, max_items=3)
    news_line = err or "; ".join(f"{it.source}: {it.title}" for it in items)
    price_line = "ETH price: n/a (test)"
    if include_llm:
        price_line = "ETH price: (skipped in test)"
    portfolio = f"ETH balance (test): {format_decimal(0.0)}"
    analysis = "stub analysis" if not include_llm else "would call llm"
    return f"{price_line}\n{portfolio}\nNews: {news_line}\nAnalysis: {analysis}"
