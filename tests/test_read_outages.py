import time
from decimal import Decimal

import pytest
from test_grid import grid_bot, grid_market

from perp_farming_bots.markets import VenueRequestError
from perp_farming_bots.models import BotState


@pytest.mark.parametrize("dependency", ["snapshot", "margin", "orders"])
async def test_transient_native_read_keeps_grid_active_and_recovers(env, monkeypatch, dependency):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    obj, method = {
        "snapshot": (adapter, "snapshot"),
        "margin": (runtime.margin, "verify"),
        "orders": (adapter, "open_orders"),
    }[dependency]
    original = getattr(obj, method)

    async def unavailable(*args, **kwargs):
        raise VenueRequestError("连接暂时断开", None)

    monkeypatch.setattr(obj, method, unavailable)
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.HOLDING
    assert not store.bot_pending(bot.id) and adapter.sent == []
    monkeypatch.setattr(obj, method, original)
    prices.update(bid=Decimal("58999"), ask=Decimal("58999.5"))
    assert await runtime.grid.tick(bot.id)
    assert len(adapter.sent) == 1


async def test_continuous_outage_pauses_after_five_minutes_without_trading(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    clock = [time.time()]
    monkeypatch.setattr("time.time", lambda: clock[0])
    prices["stale"] = True
    assert not await runtime.grid.tick(bot.id)
    clock[0] += 299
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.HOLDING
    clock[0] += 1
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.PAUSED
    prices.update(stale=False, bid=Decimal("58999"), ask=Decimal("58999.5"))
    assert not await runtime.grid.tick(bot.id) and adapter.sent == []


async def test_successful_check_resets_continuous_outage_window(env, monkeypatch):
    store, runtime, account, _ = env
    prices, _ = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    clock = [time.time()]
    monkeypatch.setattr("time.time", lambda: clock[0])
    prices["stale"] = True
    await runtime.grid.tick(bot.id)
    clock[0] += 250
    prices["stale"] = False
    await runtime.grid.tick(bot.id)
    prices["stale"] = True
    await runtime.grid.tick(bot.id)
    clock[0] += 250
    await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.HOLDING


async def test_unsent_hedge_final_read_can_retry_without_leaving_an_open_cycle(env, monkeypatch):
    from unittest.mock import AsyncMock

    from test_runtime import make_bot

    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    await runtime.command(bot.id, "run")
    original = runtime._execute
    monkeypatch.setattr(runtime, "_execute", AsyncMock(side_effect=VenueRequestError("temporary read", 503)))
    assert not await runtime.try_open(bot.id)
    assert store.bot(bot.id).state == BotState.WAITING
    assert store.cycle(bot.id)["open_operation_id"] is None and not store.bot_pending(bot.id)
    monkeypatch.setattr(runtime, "_execute", original)
    assert await runtime.try_open(bot.id)
    assert len(runtime.accounts.adapter(a.id).sent) == len(runtime.accounts.adapter(b.id).sent) == 1


async def test_scheduled_close_reads_retry_without_disarming_reopening(
    env, monkeypatch
):
    from test_reopening import configure
    from test_runtime import open_bot

    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    configure(store, bot, reopen_interval_seconds=60)
    clock = [time.time() + 61]
    monkeypatch.setattr("time.time", lambda: clock[0])
    original = runtime._check_inventory

    async def offline(*args):
        raise VenueRequestError("temporary connection failure")

    monkeypatch.setattr(runtime, "_check_inventory", offline)
    assert not await runtime.try_reopen(bot.id)
    assert store.bot(bot.id).state == BotState.HOLDING
    assert store.cycle(bot.id)["next_reopen_at"] is not None and not store.bot_pending(bot.id)
    assert len(runtime.accounts.adapter(a.id).sent) == 1
    monkeypatch.setattr(runtime, "_check_inventory", original)
    assert await runtime.try_reopen(bot.id)
    assert len(runtime.accounts.adapter(a.id).sent) == 2
    assert await runtime.try_open(bot.id) is False  # Random wait is still respected.


async def test_manual_close_disconnect_pauses_without_submitting_or_scheduling_retry(env, monkeypatch):
    from test_runtime import open_bot

    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    original = runtime._check_inventory

    async def offline(*args):
        raise VenueRequestError('temporary connection failure')

    monkeypatch.setattr(runtime, '_check_inventory', offline)
    await runtime.command(bot.id, 'close')
    assert store.bot(bot.id).state == BotState.PAUSED
    assert not store.bot_pending(bot.id) and len(runtime.accounts.adapter(a.id).sent) == 1
    monkeypatch.setattr(runtime, '_check_inventory', original)
    assert not await runtime.try_reopen(bot.id)
    assert len(runtime.accounts.adapter(a.id).sent) == 1
    await runtime.command(bot.id, 'close')
    assert store.bot(bot.id).state == BotState.CLOSED
