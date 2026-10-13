"""Monitor real strategy state without adding trading authority or synthetic orders."""

import time
from decimal import Decimal

import pytest
from test_account_form import page as page
from test_grid import grid_bot, grid_market
from test_runtime import make_bot

from perp_farming_bots.models import BotState, BotUpdate
from perp_farming_bots.strategy_widgets import (
    GridMarket,
    GridMonitor,
    HedgeMarket,
    HedgeMonitor,
    observe_strategy,
)


async def test_saved_grid_shows_required_run_action_instead_of_waiting_for_initialization(page, env):
    store, runtime, account, _ = env
    bot = grid_bot(store, account)
    runtime.last_tick = time.time()
    with page:
        monitor = GridMonitor()
    monitor.update(bot, store, await observe_strategy(runtime, bot))
    assert monitor.status.text == "待运行"
    assert "点击“运行”" in monitor.explanation.text
    assert "等待初始化" not in [value.text for value in monitor.values]
    assert monitor.rows == {} and not monitor.wall.visible
    assert store.bot(bot.id).state == BotState.READY
    assert store.grid_state(bot.id) is None and store.bot_orders(bot.id) == []
    assert runtime.accounts.adapter(account.id).sent == []
    assert runtime.accounts.adapter(account.id).margin_sent == []


async def test_neutral_wall_explains_zero_inventory_and_next_actual_lines(page, env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    runtime.last_tick = time.time()
    before = store.grid_state(bot.id), store.positions(bot.id), store.bot_orders(bot.id)
    with page:
        monitor = GridMonitor()
    monitor.update(store.bot(bot.id), store, await observe_strategy(runtime, store.bot(bot.id)))
    assert monitor.values[1].text == "$59,000.00"
    assert monitor.values[2].text == "$61,000.00"
    assert "目标仓位为 0" in monitor.explanation.text
    assert "已确认成交 0 笔" in monitor.inventory.text
    assert monitor.rows[2].status.text == "基准格线"
    assert monitor.rows[1].status.text == "下一格 · 等待触发"
    assert monitor.rows[3].status.text == "下一格 · 等待触发"
    assert monitor.rows[0].status.text == "后续格线"
    assert (store.grid_state(bot.id), store.positions(bot.id), store.bot_orders(bot.id)) == before
    assert adapter.sent == []


@pytest.mark.parametrize("direction", ["long", "short"])
async def test_wall_distinguishes_open_and_reduce_without_replacing_rows(page, env, monkeypatch, direction):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, direction)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    runtime.last_tick = time.time()
    with page:
        monitor = GridMonitor()
    monitor.update(store.bot(bot.id), store, await observe_strategy(runtime, store.bot(bot.id)))
    assert monitor.rows[1].action.text == ("买入 · 加仓" if direction == "long" else "买入 · 减仓")
    assert monitor.rows[3].action.text == ("卖出 · 减仓" if direction == "long" else "卖出 · 加仓")
    ids = {i: row.root.id for i, row in monitor.rows.items()}
    orders = list(adapter.sent)
    prices.update(bid=Decimal("60010"), ask=Decimal("60011"))
    monitor.update(store.bot(bot.id), store, await observe_strategy(runtime, store.bot(bot.id)))
    assert ids == {i: row.root.id for i, row in monitor.rows.items()}
    assert adapter.sent == orders


async def test_paused_and_unknown_quote_never_show_active_grid_triggers(page, env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    runtime.last_tick = time.time()
    await runtime.command(bot.id, "pause")
    with page:
        monitor = GridMonitor()
    monitor.update(store.bot(bot.id), store, await observe_strategy(runtime, store.bot(bot.id)))
    assert monitor.rows[1].status.text == "下一格 · 已暂停"
    assert "不会触发交易" in monitor.status.text
    store.set_state(bot.id, BotState.HOLDING, "isolated test state")
    prices["stale"] = True
    market = await observe_strategy(runtime, store.bot(bot.id))
    assert isinstance(market, GridMarket) and market.book is None
    monitor.update(store.bot(bot.id), store, market)
    assert monitor.values[0].text == "暂不可用"
    assert "距离待确认" in monitor.hints[1].text
    assert monitor.rows[1].status.text == "下一格 · 暂不执行"
    assert "旧价" in monitor.ticker_hint.text
    assert adapter.sent == []


async def test_uninitialized_grid_does_not_invent_exchange_quantized_lines(page, env):
    store, runtime, account, _ = env
    bot = grid_bot(store, account)
    with page:
        monitor = GridMonitor()
    monitor.update(bot, store, await observe_strategy(runtime, bot))
    assert monitor.rows == {} and not monitor.wall.visible and monitor.empty.visible
    assert monitor.values[1].text == "尚未生成"
    assert runtime.accounts.adapter(account.id).sent == []


async def test_hedge_uses_execution_spread_and_unavailable_quote_remains_unknown(page, env):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    bot = store.update_bot(
        bot.id,
        BotUpdate(
            name=bot.name, parameters=bot.parameters.model_copy(update={"threshold_pct": Decimal("0.05")})
        ),
    )
    await runtime.command(bot.id, "run")
    runtime.last_tick = time.time()
    with page:
        monitor = HedgeMonitor()
    market = await observe_strategy(runtime, store.bot(bot.id))
    assert isinstance(market, HedgeMarket) and market.preview is not None
    monitor.update(store.bot(bot.id), store, market)
    assert monitor.values[0].text.startswith("-0.0017")
    assert monitor.status.text == "等待价差达到建仓条件"
    expired = HedgeMarket(
        market.preview.model_copy(update={"received_at": time.time() - 60}), None, runtime.last_tick
    )
    monitor.update(store.bot(bot.id), store, expired)
    assert monitor.values[0].text == "暂不可用" and monitor.hints[0].text == "报价已过期"
    runtime.markets.stale = True
    market = await observe_strategy(runtime, store.bot(bot.id))
    monitor.update(store.bot(bot.id), store, market)
    assert monitor.values[0].text == "暂不可用"
    assert monitor.status.text == "报价暂不可用"
    assert runtime.accounts.adapter(a.id).sent == runtime.accounts.adapter(b.id).sent == []
