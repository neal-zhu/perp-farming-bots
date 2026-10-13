import json
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from test_runtime import make_bot

from perp_farming_bots import markets as markets_module
from perp_farming_bots.markets import Markets
from perp_farming_bots.models import MarketSpec, Provider


def spec(provider):
    return MarketSpec(
        provider=provider,
        symbol="BTC",
        native_symbol="BTC",
        market_id=1,
        quantity_step="0.001",
        price_tick="0.1",
        min_quantity="0.001",
        min_notional="5",
    )


async def test_arcus_fraction_is_converted_to_hourly_percent_and_failure_never_returns_cached_rate(
    monkeypatch,
):
    markets = Markets()
    monkeypatch.setattr(markets, "spec", AsyncMock(return_value=spec(Provider.ARCUS)))
    request = AsyncMock(
        return_value={
            "markets": [
                {"marketId": 2, "baseAsset": "ETH", "fundingRate": "0.5"},
                {
                    "marketId": 1,
                    "baseAsset": "BTC",
                    "fundingRate": "0.0000125",
                    "nextFundingRate": "-0.00002",
                    "nextFundingAt": time.time() + 600,
                },
            ]
        }
    )
    monkeypatch.setattr(markets, "request", request)
    result = await markets.funding(Provider.ARCUS, "BTC")
    assert result.predicted_rate_pct == Decimal("-0.002")
    assert result.last_rate_pct == Decimal("0.00125")
    assert result.interval_seconds == 3600
    assert (await markets.funding(Provider.ARCUS, "BTC")) == result
    assert request.await_count == 1
    markets.funding_checked[Provider.ARCUS, "BTC"] -= 31
    request.side_effect = ValueError("官方接口不可用")
    missing = await markets.funding(Provider.ARCUS, "BTC")
    assert missing.status == "unavailable"
    assert missing.predicted_rate_pct is missing.last_rate_pct is None
    assert missing.received_at is None
    await markets.close()


@pytest.mark.parametrize("provider", [Provider.LIGHTER, Provider.LIGHTER_RH])
@pytest.mark.parametrize("invalid", [None, "wrong-market", "stale", "future"])
async def test_lighter_native_stream_uses_percent_and_checks_identity_and_timestamp(
    monkeypatch, provider, invalid
):
    markets = Markets()
    monkeypatch.setattr(markets, "spec", AsyncMock(return_value=spec(provider)))
    now = time.time()
    message = {
        "channel": "market_stats:1",
        "timestamp": int((now + {"stale": -120, "future": 120}.get(invalid, 0)) * 1000),
        "market_stats": {
            "market_id": 1,
            "symbol": "ETH" if invalid == "wrong-market" else "BTC",
            "current_funding_rate": "0.0012",
            "funding_rate": "-0.0006",
            "funding_timestamp": int((now - 100) * 1000),
        },
    }

    class Socket:
        send = AsyncMock()

        async def __aiter__(self):
            yield json.dumps({"type": "ping"})
            yield json.dumps({"channel": "market_stats:2"})
            yield json.dumps(message)

    urls = []

    @asynccontextmanager
    async def connect(url, **kwargs):
        urls.append(url)
        yield Socket()

    monkeypatch.setattr(markets_module, "connect", connect)
    result = await markets.funding(provider, "BTC")
    assert urls == [markets_module.HOSTS[provider].replace("https://", "wss://") + "/stream?readonly=true"]
    if invalid:
        assert result.status == "unavailable"
        assert result.predicted_rate_pct is result.last_rate_pct is None
        if invalid == "stale":
            assert result.unavailable_reason == "资金费率数据已过期"
        elif invalid == "future":
            assert result.unavailable_reason == "资金费率时间戳异常：交易所时间领先本机超过 5 秒"
    else:
        assert result.predicted_rate_pct == Decimal("0.0012")
        assert result.last_rate_pct == Decimal("-0.0006")
        assert result.next_payment_at == int(now - 100) + 3600
    await markets.close()


@pytest.mark.parametrize("provider", [Provider.LIGHTER, Provider.LIGHTER_RH])
async def test_lighter_fresh_snapshot_allows_small_upstream_clock_lead(monkeypatch, provider):
    # Live Core and RH snapshots led the receiving machine by about 70 ms.
    # Replay that native pattern with a fixed clock, without network timing.
    now = 1791812667.100
    monkeypatch.setattr(markets_module.time, "time", lambda: now)
    markets = Markets()
    monkeypatch.setattr(markets, "spec", AsyncMock(return_value=spec(provider)))
    message = {
        "type": "subscribed/market_stats",
        "channel": "market_stats:1",
        "timestamp": 1791812667173,
        "market_stats": {
            "market_id": 1,
            "symbol": "BTC",
            "current_funding_rate": "0.0012",
            "funding_rate": "0.0012",
            "funding_timestamp": 1791810000000,
        },
    }

    class Socket:
        send = AsyncMock()

        async def __aiter__(self):
            yield json.dumps(message)

    @asynccontextmanager
    async def connect(url, **kwargs):
        yield Socket()

    monkeypatch.setattr(markets_module, "connect", connect)
    try:
        result = await markets.funding(provider, "BTC")
        assert result.status == "available", result.unavailable_reason
        assert result.predicted_rate_pct == Decimal("0.0012")
        assert result.last_rate_pct == Decimal("0.0012")
        assert result.next_payment_at == 1791813600
    finally:
        await markets.close()


async def test_net_funding_is_short_minus_long_and_unknown_leg_prevents_estimate(env, monkeypatch):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    long = await runtime.markets.funding(a.provider, "BTC")
    short = long.model_copy(update={"predicted_rate_pct": Decimal("-0.0020")})
    monkeypatch.setattr(runtime.markets, "funding", AsyncMock(side_effect=[long, short]))
    assert (await runtime.funding(bot.id))["net_receipt_rate_pct"] == "-0.0032"
    missing = long.model_copy(
        update={
            "status": "unavailable",
            "predicted_rate_pct": None,
            "last_rate_pct": None,
            "next_payment_at": None,
            "received_at": None,
            "unavailable_reason": "网络错误",
        }
    )
    monkeypatch.setattr(runtime.markets, "funding", AsyncMock(side_effect=[long, missing]))
    result = await runtime.funding(bot.id)
    assert result["net_receipt_rate_pct"] is None
    assert result["short"]["predicted_rate_pct"] is None
