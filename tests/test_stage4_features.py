"""Stage 4: portfolio, quick intent, alerts, digest, news aggregate, formatting."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.agent_modes import AGENT_MODE_AGENT, AGENT_MODE_DEFAULT
from app.core.alert_logic import (
    MAX_ETH_USD_ALERT,
    parse_positive_usd_price,
    resolve_alert_direction,
)
from app.core.context_builder import ContextBuilder
from app.core.news.providers import aggregate as agg_mod
from app.core.news.schemas import NewsItem
from app.core.quick_intent import classify_quick_intent
from app.core.services.digest_body import digest_already_sent_for_utc_day
from app.bot.handlers.portfolio_helpers import parse_add_eth_amount
from app.utils.formatting import format_decimal, format_percent


def test_parse_add_eth_valid() -> None:
    v, err = parse_add_eth_amount("0.25")
    assert err is None
    assert v == Decimal("0.25")


@pytest.mark.parametrize(
    "raw",
    ["", "  ", "0", "-1", "abc", "1e309"],
)
def test_parse_add_eth_invalid(raw: str) -> None:
    v, err = parse_add_eth_amount(raw)
    assert v is None
    assert err


def test_parse_add_eth_too_large() -> None:
    v, err = parse_add_eth_amount("999999999")
    assert v is None


def test_parse_alert_price() -> None:
    assert parse_positive_usd_price("")[0] is None
    assert parse_positive_usd_price("0")[0] is None
    assert parse_positive_usd_price("-5")[0] is None
    v, err = parse_positive_usd_price("3500.5")
    assert err is None
    assert v == Decimal("3500.5")


def test_parse_alert_max() -> None:
    v, _ = parse_positive_usd_price(str(MAX_ETH_USD_ALERT))
    assert v == MAX_ETH_USD_ALERT
    assert parse_positive_usd_price(str(MAX_ETH_USD_ALERT + 1))[0] is None


def test_resolve_alert_direction() -> None:
    assert resolve_alert_direction(target=Decimal("2"), current=Decimal("1")) == (
        "above",
        None,
    )
    assert resolve_alert_direction(target=Decimal("1"), current=Decimal("2")) == (
        "below",
        None,
    )
    d, err = resolve_alert_direction(target=Decimal("5"), current=Decimal("5"))
    assert d is None
    assert err


def test_quick_intent_portfolio() -> None:
    qi = classify_quick_intent(
        "сколько у меня ETH",
        active_mode=AGENT_MODE_DEFAULT,
    )
    assert qi.matched and qi.kind == "portfolio"


def test_quick_intent_crypto_market() -> None:
    qi = classify_quick_intent(
        "что по рынку",
        active_mode=AGENT_MODE_DEFAULT,
    )
    assert qi.matched and qi.kind == "crypto_market"


def test_one_shot_crypto_leaves_conversation_patch_empty() -> None:
    from app.core.agent_modes import resolve_runtime_context

    class _Conv:
        active_mode = AGENT_MODE_DEFAULT
        active_agent_id = "general"
        active_skill_id = "chat"
        active_model_id = "default_balanced"

    ctx = resolve_runtime_context(
        conversation=_Conv(),  # type: ignore[arg-type]
        message_text="что по рынку",
        one_shot_agent_id="crypto",
    )
    assert ctx.agent_profile.id == "crypto"
    assert ctx.is_one_shot is True
    assert ctx.conversation_patch == {}


def test_quick_intent_disabled_in_agent_mode() -> None:
    qi = classify_quick_intent(
        "мой портфель",
        active_mode=AGENT_MODE_AGENT,
    )
    assert not qi.matched


def test_digest_same_utc_day() -> None:
    ts = datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)
    day = ts.date()
    assert digest_already_sent_for_utc_day(last_sent_at=ts, utc_day=day)


def test_digest_different_day() -> None:
    ts = datetime(2026, 4, 27, 23, 0, tzinfo=timezone.utc)
    assert not digest_already_sent_for_utc_day(
        last_sent_at=ts,
        utc_day=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc).date(),
    )


@pytest.mark.asyncio
async def test_aggregate_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty_cp(**_kwargs):  # noqa: ANN003
        return []

    async def empty_rss(**_kwargs):  # noqa: ANN003
        return []

    monkeypatch.setattr(agg_mod, "fetch_cryptopanic_news", empty_cp)
    monkeypatch.setattr(agg_mod, "fetch_all_rss_news", empty_rss)
    out = await agg_mod.aggregate_crypto_news()
    assert len(out) == 1
    assert "недоступн" in out[0].title.lower() or "недоступн" in out[0].title


@pytest.mark.asyncio
async def test_context_builder_crypto_context_block(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.context_builder as cb_module

    class _FakeRepo:
        async def list_recent_for_agent(self, **_kwargs):  # noqa: ANN003
            return []

    monkeypatch.setattr(cb_module, "MessageRepository", lambda _s: _FakeRepo())
    builder = ContextBuilder(session=None)  # type: ignore[arg-type]
    from app.agents.registry import get_agent_registry

    agent = get_agent_registry().get("crypto")

    class _Conv:
        id = uuid4()

    block = "=== Factual context ===\nTEST"
    msgs = await builder.build_messages(
        conversation=_Conv(),  # type: ignore[arg-type]
        agent=agent,
        history_agent_id="crypto",
        crypto_context_block=block,
    )
    assert msgs[0]["role"] == "system"
    assert msgs[1] == {"role": "user", "content": block}


def test_format_decimal() -> None:
    assert format_decimal(Decimal("1.2300")) == "1.23"
    assert "1" in format_decimal(Decimal("1"))


def test_format_percent() -> None:
    assert format_percent(Decimal("0.0525")) == "5.25%"


def test_russian_unicode_safe_format() -> None:
    s = "Привет, мир — €100"
    assert "Привет" in s


@pytest.mark.asyncio
async def test_rss_parser_uses_title_link(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from app.core.news.providers import rss as rss_mod

    xml = b"""<?xml version="1.0"?>
    <rss><channel>
      <item><title>Hello &amp; World</title><link>https://example.com/a</link></item>
    </channel></rss>"""

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        content = xml

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=_Resp())

    items = await rss_mod.fetch_rss_feed("https://test/rss", client=client, per_feed_limit=5)
    assert len(items) == 1
    assert items[0].title
    assert items[0].url.startswith("https://")
