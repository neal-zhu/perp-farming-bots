"""Known liquidity shortages wait; missing order evidence never enables replay."""

import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from test_grid import grid_bot, grid_market
from test_reopening import configure
from test_runtime import make_bot, open_bot

from perp_farming_bots.markets import Markets, QuoteUnavailable
from perp_farming_bots.models import BotState, InsufficientLiquidity, Provider
from perp_farming_bots.store import alerts, operations


@pytest.mark.parametrize("initialized", [False, True])
@pytest.mark.parametrize("phase", ["planning", "final_quote"])
async def test_grid_waits_through_thin_depth_and_trades_original_size_after_recovery(
    env, monkeypatch, initialized, phase
):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    if initialized:
        assert await runtime.grid.tick(bot.id)
        prices.update(bid=Decimal("58999"), ask=Decimal("58999.5"))
    before = store.grid_state(bot.id), store.positions(bot.id), store.bot_orders(bot.id)
    sent = len(adapter.sent)
    original = runtime.markets.book

    async def thin_depth(provider, symbol, *, refresh=False):
        book = await original(provider, symbol, refresh=refresh)
        if phase == "planning" or any(op["status"] == "pending" for op in store.rows(operations, bot.id)):
            book.bids[0].quantity = book.asks[0].quantity = Decimal("0.000001")
        return book

    monkeypatch.setattr(runtime.markets, "book", thin_depth)
    clock = [time.time()]
    monkeypatch.setattr("time.time", lambda: clock[0])
    for _ in range(3):
        assert not await runtime.grid.tick(bot.id)
        assert store.bot(bot.id).state == (BotState.HOLDING if initialized else BotState.WAITING)
        assert (store.grid_state(bot.id), store.positions(bot.id), store.bot_orders(bot.id)) == before
        assert not store.bot_pending(bot.id) and len(adapter.sent) == sent
        clock[0] += 301
    assert store.rows(alerts, bot.id) == []
    monkeypatch.setattr(runtime.markets, "book", original)
    assert await runtime.grid.tick(bot.id) and len(adapter.sent) == sent + 1
    assert adapter.sent[-1].quantity == Decimal("0.01" if initialized else "0.02")


@pytest.mark.parametrize("side", ["bids", "asks"])
async def test_public_empty_book_waits_without_returning_cached_price(env, monkeypatch, side):
    _, runtime, _, _ = env
    markets = runtime.markets
    native = {"bids": [["59999", "1"]], "asks": [["60000", "1"]], "timestamp": int(time.time() * 1_000_000)}
    native[side] = []
    monkeypatch.setattr(markets, "request", AsyncMock(return_value=native))
    # First retain an actual fixture quote to ensure an unavailable refresh does
    # not silently reuse it as current executable data.
    markets.cache[(Provider.ARCUS, "BTC")] = await markets.book(Provider.ARCUS, "BTC")
    with pytest.raises(InsufficientLiquidity, match="暂时没有双边报价"):
        await Markets.book(markets, Provider.ARCUS, "BTC", refresh=True)


async def test_crossed_public_book_is_explicitly_unavailable_and_can_refresh(env, monkeypatch):
    _, runtime, _, _ = env
    markets = runtime.markets
    native = {"bids": [["60001", "1"]], "asks": [["60000", "1"]], "timestamp": int(time.time() * 1_000_000)}
    monkeypatch.setattr(markets, "request", AsyncMock(return_value=native))
    with pytest.raises(QuoteUnavailable, match="价格交叉"):
        await Markets.book(markets, Provider.ARCUS, "BTC", refresh=True)
    native["bids"] = [["59999", "1"]]
    book = await Markets.book(markets, Provider.ARCUS, "BTC", refresh=True)
    assert book.bids[0].price == Decimal("59999")


async def test_liquidity_recovery_does_not_resume_manually_paused_grid(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    original = runtime.markets.book

    async def no_quote(*args, **kwargs):
        raise InsufficientLiquidity("盘口暂时没有双边报价")

    monkeypatch.setattr(runtime.markets, "book", no_quote)
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.HOLDING
    await runtime.command(bot.id, "pause")
    monkeypatch.setattr(runtime.markets, "book", original)
    prices.update(bid=Decimal("58999"), ask=Decimal("58999.5"))
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.PAUSED and len(adapter.sent) == 1


@pytest.mark.parametrize("phase", ["planning", "final_quote"])
async def test_hedge_waits_if_depth_disappears_before_first_order(env, monkeypatch, phase):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    await runtime.command(bot.id, "run")
    original = runtime.markets.book

    async def thin_depth(provider, symbol, *, refresh=False):
        book = await original(provider, symbol, refresh=refresh)
        if phase == "planning" or store.bot_pending(bot.id):
            book.bids[0].quantity = book.asks[0].quantity = Decimal("0.000001")
        return book

    monkeypatch.setattr(runtime.markets, "book", thin_depth)
    for _ in range(2):
        assert not await runtime.try_open(bot.id)
        assert store.bot(bot.id).state == BotState.WAITING
        assert not store.positions(bot.id) and not store.bot_orders(bot.id)
        assert not store.bot_pending(bot.id)
        assert runtime.accounts.adapter(a.id).sent == runtime.accounts.adapter(b.id).sent == []
    assert store.rows(alerts, bot.id) == []
    if phase == "final_quote":
        assert all(op["status"] == "skipped" for op in store.rows(operations, bot.id))
    monkeypatch.setattr(runtime.markets, "book", original)
    assert await runtime.try_open(bot.id)
    assert len(runtime.accounts.adapter(a.id).sent) == len(runtime.accounts.adapter(b.id).sent) == 1
    assert len(store.positions(bot.id)) == 2


async def test_hedge_losing_depth_after_first_fill_retains_exposure_and_never_replays(env, monkeypatch):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    await runtime.command(bot.id, "run")
    original = runtime.markets.book

    async def second_leg_depth_disappears(provider, symbol, *, refresh=False):
        book = await original(provider, symbol, refresh=refresh)
        if runtime.accounts.adapter(a.id).sent:
            book.bids[0].quantity = Decimal("0.000001")
        return book

    monkeypatch.setattr(runtime.markets, "book", second_leg_depth_disappears)
    assert not await runtime.try_open(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION
    assert "盘口深度" in store.bot(bot.id).reason
    assert len(store.bot_orders(bot.id)) == len(store.positions(bot.id)) == 1
    assert store.rows(operations, bot.id)[0]["status"] == "attention"
    monkeypatch.setattr(runtime.markets, "book", original)
    assert not await runtime.try_open(bot.id)
    await runtime.sync(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION
    assert len(runtime.accounts.adapter(a.id).sent) == 1 and runtime.accounts.adapter(b.id).sent == []


@pytest.mark.parametrize("reopen", [False, True])
@pytest.mark.parametrize("phase", ["planning", "final_quote"])
async def test_close_depth_shortage_retains_inventory_and_only_scheduled_close_retries(
    env, monkeypatch, reopen, phase
):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    if reopen:
        configure(store, bot, reopen_interval_seconds=60)
        clock = time.time() + 61
        monkeypatch.setattr("time.time", lambda: clock)
    before = store.positions(bot.id), store.bot_orders(bot.id)
    due = store.cycle(bot.id)["next_reopen_at"]
    original = runtime.markets.book

    async def thin_depth(provider, symbol, *, refresh=False):
        book = await original(provider, symbol, refresh=refresh)
        calls[0] += 1
        if phase == "planning" or calls[0] >= 3:
            book.bids[0].quantity = book.asks[0].quantity = Decimal("0.000001")
        return book

    calls = [0]
    monkeypatch.setattr(runtime.markets, "book", thin_depth)
    if reopen:
        assert not await runtime.try_reopen(bot.id)
    else:
        await runtime.command(bot.id, "close")
    assert store.bot(bot.id).state == (BotState.HOLDING if reopen else BotState.PAUSED)
    assert (store.positions(bot.id), store.bot_orders(bot.id)) == before
    assert not store.bot_pending(bot.id)
    assert store.rows(operations, bot.id)[0]["status"] == "skipped"
    if reopen:
        assert store.cycle(bot.id)["next_reopen_at"] == due
    monkeypatch.setattr(runtime.markets, "book", original)
    if reopen:
        assert await runtime.try_reopen(bot.id)
    else:
        assert not await runtime.try_reopen(bot.id)
        assert (store.positions(bot.id), store.bot_orders(bot.id)) == before
        await runtime.command(bot.id, "close")
        assert store.bot(bot.id).state == BotState.CLOSED
    assert store.positions(bot.id) == []
    assert len(runtime.accounts.adapter(a.id).sent) == len(runtime.accounts.adapter(b.id).sent) == 2
