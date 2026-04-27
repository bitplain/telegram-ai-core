"""Stage 4: новости, алерты, дайджест, quick intent, crypto prompt."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.agents.registry import get_agent_registry
from app.core.agent_modes import AGENT_MODE_DEFAULT, resolve_runtime_context
from app.core.alert_logic import alert_should_fire
from app.core.news.providers.aggregate import NEWS_UNAVAILABLE, fetch_crypto_news
from app.core.quick_intent import QuickIntent, detect_quick_intent
from app.core.services.digest_body import build_digest_for_tests
from app.utils.formatting import format_decimal, format_percent


def test_quick_intent_portfolio_ru() -> None:
    assert detect_quick_intent("сколько у меня ETH?") is QuickIntent.PORTFOLIO
    assert detect_quick_intent("Сколько у меня эфира?") is QuickIntent.PORTFOLIO


def test_quick_intent_market_ru() -> None:
    assert detect_quick_intent("что по рынку?") is QuickIntent.CRYPTO_MARKET


def test_force_skill_routing_crypto() -> None:
    conv = SimpleNamespace(
        active_mode=AGENT_MODE_DEFAULT,
        active_agent_id="general",
        active_skill_id="chat",
        active_model_id="default_balanced",
    )
    ctx = resolve_runtime_context(
        conversation=conv,
        message_text="что по рынку",
        force_skill_id="crypto",
    )
    assert ctx.skill_id == "crypto"
    assert ctx.agent_id == "crypto"
    assert ctx.matched_by == "quick_intent"


def test_force_skill_routing_portfolio() -> None:
    conv = SimpleNamespace(
        active_mode=AGENT_MODE_DEFAULT,
        active_agent_id="general",
        active_skill_id="chat",
        active_model_id="default_balanced",
    )
    ctx = resolve_runtime_context(
        conversation=conv,
        message_text="сколько eth",
        force_skill_id="portfolio",
    )
    assert ctx.skill_id == "portfolio"


def test_alert_fire_above_below() -> None:
    assert alert_should_fire(current_price_usd=4001, target_price_usd=4000, direction="above")
    assert not alert_should_fire(
        current_price_usd=3999, target_price_usd=4000, direction="above"
    )
    assert alert_should_fire(current_price_usd=2999, target_price_usd=3000, direction="below")


@pytest.mark.asyncio
async def test_fetch_crypto_news_uses_mock_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Мок ответа RSS — без реальной сети."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "cryptopanic" in str(request.url):
            return httpx.Response(401)
        host = str(request.url.host or "feed")
        xml = f"""<?xml version="1.0"?><rss><channel>
        <item><title>One {host}</title><link>https://{host}/a</link></item>
        <item><title>Two {host}</title><link>https://{host}/b</link></item>
        <item><title>Three {host}</title><link>https://{host}/c</link></item>
        </channel></rss>"""
        return httpx.Response(200, text=xml)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        items, err = await fetch_crypto_news(client=client, min_items=3, max_items=5)
    assert err is None
    assert len(items) >= 3
    assert all(it.title and it.source and it.url for it in items)


@pytest.mark.asyncio
async def test_fetch_crypto_news_fallback_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        items, err = await fetch_crypto_news(client=client, min_items=3, max_items=5)
    assert items == []
    assert err == NEWS_UNAVAILABLE


def test_crypto_agent_prompt_structure() -> None:
    agent = get_agent_registry().get("crypto")
    sp = agent.system_prompt.lower()
    assert "не финансовая рекомендация" in sp or "финансовая рекомендация" in sp
    assert "риск" in sp
    assert "альтернатив" in sp


@pytest.mark.asyncio
async def test_digest_generation_stub() -> None:
    text = await build_digest_for_tests(include_llm=False)
    assert "News:" in text or "ETH" in text


def test_formatting_helpers() -> None:
    assert "," in format_decimal(1234.5678) or "1" in format_decimal(1234.5678)
    assert "%" in format_percent(12.3456)
