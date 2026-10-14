"""Native ticker selection and unequal-quantity hedge lifecycle, using isolated doubles."""

import asyncio
import time
from decimal import Decimal

import httpx
import pytest
from nicegui import ui
from pydantic import ValidationError
from sqlalchemy import update
from test_account_form import page as page
from test_grid import grid_bot

from perp_farming_bots.market_ui import MarketSelector
from perp_farming_bots.markets import Markets
from perp_farming_bots.models import (
    Book,
    BotCreate,
    BotState,
    GridParameters,
    HedgeParameters,
    Level,
    NativePosition,
    Provider,
)
from perp_farming_bots.store import bot_cycles


def selected_pair(store, a, b, **changes):
    return store.add_bot(
        BotCreate(
            name="Independent tickers",
            request_id="independent-tickers",
            parameters=HedgeParameters(
                **{
                    "long_connection_id": a.id,
                    "short_connection_id": b.id,
                    "long_symbol": "BTC",
                    "short_symbol": "io:OAI",
                    "threshold_pct": "-98",
                    "target_usd": "600",
                    **changes,
                }
            ),
        )
    )


async def distinct_native_markets(runtime, a, b, monkeypatch):
    prices = {"BTC": (Decimal("59999.9"), Decimal("60000")), "io:OAI": (Decimal("1500"), Decimal("1500.1"))}
    original_spec = runtime.markets.spec

    async def spec(provider, symbol):
        result = await original_spec(provider, symbol)
        return result.model_copy(update={"quantity_step": Decimal("0.001" if symbol == "BTC" else "0.01")})

    async def book(provider, symbol, *, refresh=False):
        bid, ask = prices[symbol]
        return Book(
            provider=provider,
            symbol=symbol,
            bids=[Level(price=bid, quantity=1000)],
            asks=[Level(price=ask, quantity=1000)],
            received_at=time.time(),
            source="native test book",
        )

    monkeypatch.setattr(runtime.markets, "spec", spec)
    monkeypatch.setattr(runtime.markets, "book", book)
    for connection in [a, b]:
        adapter = runtime.accounts.adapter(connection.id)
        original_send, original_snapshot = adapter.send, adapter.snapshot

        async def send(prepared, adapter=adapter, original_send=original_send):
            native_id = await original_send(prepared)
            intent = adapter.sent[-1]
            result = adapter.results[intent.client_id]
            if result.quantity:
                result.average_price = prices[intent.symbol][1 if intent.side == "buy" else 0]
            return native_id

        async def snapshot(adapter=adapter, original_snapshot=original_snapshot):
            result = await original_snapshot()
            nets = {}
            for intent in adapter.sent:
                native = adapter.results[intent.client_id]
                nets[intent.symbol] = nets.get(intent.symbol, Decimal(0)) + native.quantity * (
                    1 if intent.side == "buy" else -1
                )
            return result.model_copy(
                update={
                    "positions": [
                        NativePosition(
                            symbol=symbol, quantity=quantity, entry_price=prices[symbol][0], unrealized_pnl=0
                        )
                        for symbol, quantity in nets.items()
                        if quantity
                    ]
                }
            )

        monkeypatch.setattr(adapter, "send", send)
        monkeypatch.setattr(adapter, "snapshot", snapshot)


@pytest.mark.parametrize("partial_first", [False, True])
async def test_distinct_tickers_size_each_leg_and_resume_close_reopen(env, monkeypatch, partial_first):
    store, runtime, a, b = env
    await distinct_native_markets(runtime, a, b, monkeypatch)
    if partial_first:
        runtime.accounts.adapter(a.id).fraction = Decimal("0.5")
    bot = selected_pair(store, a, b, reopen_interval_seconds=60, reopen_random_wait_seconds=0)
    preview = await runtime.preview(bot)
    assert preview.long_quantity == Decimal("0.01") and preview.short_quantity == Decimal("0.4")
    assert (await runtime.funding(bot.id))["short"]["symbol"] == "io:OAI"
    await runtime.command(bot.id, "run")
    assert await runtime.try_open(bot.id)
    first, second = runtime.accounts.adapter(a.id).sent[0], runtime.accounts.adapter(b.id).sent[0]
    assert first.symbol == "BTC" and second.symbol == "io:OAI"
    assert second.quantity == (Decimal("0.2") if partial_first else Decimal("0.4"))
    assert store.bot(bot.id).state == BotState.HOLDING and runtime._hedge_complete(bot.id)
    await runtime.command(bot.id, "pause")
    await runtime.command(bot.id, "run")
    assert len(runtime.accounts.adapter(a.id).sent) == len(runtime.accounts.adapter(b.id).sent) == 1
    runtime.accounts.adapter(a.id).fraction = Decimal(1)
    with store.transaction() as db:
        db.execute(
            update(bot_cycles).where(bot_cycles.c.bot_id == bot.id).values(next_reopen_at=time.time() - 1)
        )
    assert await runtime.try_reopen(bot.id)
    assert store.positions(bot.id) == [] and store.bot(bot.id).state == BotState.WAITING
    assert runtime.accounts.adapter(a.id).sent[-1].symbol == "BTC"
    assert runtime.accounts.adapter(b.id).sent[-1].symbol == "io:OAI"
    assert all(
        adapter.sent[-1].reduce_only
        for adapter in [runtime.accounts.adapter(a.id), runtime.accounts.adapter(b.id)]
    )
    assert await runtime.try_open(bot.id)
    await runtime.command(bot.id, "close")
    assert store.bot(bot.id).state == BotState.CLOSED and not store.positions(bot.id)


async def test_distinct_ticker_peer_partial_stays_attention_after_sync(env, monkeypatch):
    store, runtime, a, b = env
    await distinct_native_markets(runtime, a, b, monkeypatch)
    runtime.accounts.adapter(b.id).fraction = Decimal("0.5")
    bot = selected_pair(store, a, b)
    await runtime.command(bot.id, "run")
    assert not await runtime.try_open(bot.id)
    await runtime.sync(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION and not runtime._hedge_complete(bot.id)
    assert len(runtime.accounts.adapter(a.id).sent) == len(runtime.accounts.adapter(b.id).sent) == 1


async def test_grid_reservation_matches_exact_account_ticker_of_either_leg(env):
    store, _, a, b = env
    grid_bot(store, a, symbol="io:OAI")
    selected_pair(store, a, b)  # Same ticker on the OTHER account is independent.
    with pytest.raises(ValueError, match="独占"):
        grid_bot(store, b, symbol="io:OAI")


def test_ticker_models_preserve_native_names_without_asset_matching():
    p = HedgeParameters(
        long_connection_id="a",
        short_connection_id="b",
        long_symbol="  kPEPE ",
        short_symbol="io:OAI",
        threshold_pct=5000,
        target_usd=100,
    )
    assert p.long_symbol == "kPEPE" and p.short_symbol == "io:OAI"
    assert p.market_bindings == [("a", "kPEPE"), ("b", "io:OAI")]
    with pytest.raises(ValidationError):
        HedgeParameters(
            long_connection_id="a", short_connection_id="b", symbol="BTC", threshold_pct=0, target_usd=100
        )
    grid = GridParameters(
        connection_id="a",
        symbol="io:OAI",
        direction="long",
        lower_price=1000,
        upper_price=2000,
        grid_count=20,
        open_position_on_start=False,
        capital={"investment_usd": 300, "leverage": 3, "margin_mode": "isolated"},
    )
    assert grid.symbol == "io:OAI"
    for invalid in [None, 123, "", "A B"]:
        with pytest.raises(ValidationError):
            HedgeParameters(
                long_connection_id="a",
                short_connection_id="b",
                long_symbol=invalid,
                short_symbol="io:OAI",
                threshold_pct=0,
                target_usd=100,
            )


async def test_native_catalog_does_not_filter_asset_category_or_multiplier():
    markets = Markets()
    await markets.http.aclose()
    arcus = {
        "type": "PERPETUAL",
        "status": "ONLINE",
        "category": "RWA",
        "baseAsset": "AAPL",
        "marketId": 5,
        "marketDisplayName": "AAPL-USD",
        "stepSize": "0.01",
        "tickSize": "0.01",
        "minOrderSize": "0.01",
        "minOrderNotional": "5",
        "tickTiers": [],
    }
    lighter = {
        "market_type": "perp",
        "status": "active",
        "symbol": "1000PEPE",
        "multiplier": 1000,
        "market_id": 7,
        "supported_size_decimals": 1,
        "supported_price_decimals": 6,
        "min_base_amount": "0.1",
        "min_quote_amount": "5",
    }
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={"markets": [arcus]}
            if request.url.path == "/v1/markets"
            else {"code": 200, "order_book_details": [lighter]},
        )

    markets.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        assert await markets.catalog(Provider.ARCUS) == ["AAPL"]
        assert await markets.catalog(Provider.LIGHTER) == ["1000PEPE"]
        assert (await markets.spec(Provider.LIGHTER, "1000PEPE")).quantity_step == Decimal("0.1")
        assert len(calls) == 2
        arcus["baseAsset"] = "MSFT"
        assert await markets.catalog(Provider.ARCUS, refresh=True) == ["MSFT"]
        with pytest.raises(ValueError, match="没有所选"):
            await markets.spec(Provider.ARCUS, "AAPL")
    finally:
        await markets.close()


async def test_market_selector_discards_late_response_from_previous_account(page, env, monkeypatch):
    store, runtime, a, b = env
    entered, release = asyncio.Event(), asyncio.Event()

    async def catalog(provider, *, refresh=False):
        entered.set()
        await release.wait()
        return ["OLD"]

    monkeypatch.setattr(runtime.markets, "catalog", catalog)
    with page:
        account = ui.select({a.id: a.name, b.id: b.name}, value=a.id)
        selector = MarketSelector(store, runtime.markets, account, label="native ticker")
    task = asyncio.create_task(selector.load())
    await entered.wait()
    account.set_value(b.id)
    release.set()
    await task
    assert selector.loaded_account is None and selector.select.value is None


async def test_market_selector_searches_all_native_symbols_and_failure_is_explicit(page, env, monkeypatch):
    store, runtime, a, _ = env

    async def catalog(provider, *, refresh=False):
        return ["DOGE", "io:OAI", "kPEPE"]

    monkeypatch.setattr(runtime.markets, "catalog", catalog)
    with page:
        account = ui.select({a.id: a.name}, value=a.id)
        selector = MarketSelector(store, runtime.markets, account, label="native ticker")
    await selector.load()
    assert selector.select.options == ["DOGE", "io:OAI", "kPEPE"]
    selector.select.set_value("io:OAI")
    assert selector.valid()

    async def unavailable(provider, *, refresh=False):
        raise ValueError("catalog unavailable")

    monkeypatch.setattr(runtime.markets, "catalog", unavailable)
    await selector.load(refresh=True)
    assert not selector.valid() and selector.select.value is None
    assert selector.status.text == "catalog unavailable"
