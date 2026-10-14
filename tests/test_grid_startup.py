"""Starting flat is durable strategy state, not a deferred bulk entry."""

import time
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from pydantic import ValidationError
from test_account_form import page as page
from test_grid import grid_bot, grid_market

from perp_farming_bots.grid_ui import grid_dialog
from perp_farming_bots.models import BotState, BotUpdate, GridParameters
from perp_farming_bots.runtime import Runtime
from perp_farming_bots.store import Store
from perp_farming_bots.strategy_widgets import GridMonitor, observe_strategy


@pytest.mark.parametrize("direction", ["long", "short"])
async def test_flat_start_waits_then_buys_and_sells_single_units_without_reversing(
    env, monkeypatch, direction
):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, direction, open_position_on_start=False)
    preview = await runtime.preview(bot)
    assert preview.initial_quantity == 0 and preview.zero_inventory_cursor == 2
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    assert adapter.sent == [] and store.positions(bot.id) == []
    original = store.grid_state(bot.id)
    wrong = ("61000.5", "61001") if direction == "long" else ("58999", "58999.5")
    entry = ("58999", "58999.5") if direction == "long" else ("61000.5", "61001")
    exit_price = ("60000.5", "60001") if direction == "long" else ("59999", "59999.5")
    prices.update(bid=Decimal(wrong[0]), ask=Decimal(wrong[1]))
    assert not await runtime.grid.tick(bot.id)
    assert store.grid_state(bot.id) == original and adapter.sent == []
    prices.update(bid=Decimal(entry[0]), ask=Decimal(entry[1]))
    assert await runtime.grid.tick(bot.id)
    assert abs(adapter.net) == preview.quantity_per_grid
    assert adapter.sent[-1].quantity == preview.quantity_per_grid and not adapter.sent[-1].reduce_only
    await runtime.command(bot.id, "pause")
    await runtime.command(bot.id, "run")
    prices.update(bid=Decimal(exit_price[0]), ask=Decimal(exit_price[1]))
    assert await runtime.grid.tick(bot.id)
    assert adapter.net == 0 and adapter.sent[-1].reduce_only
    prices.update(bid=Decimal(wrong[0]), ask=Decimal(wrong[1]))
    assert not await runtime.grid.tick(bot.id) and len(adapter.sent) == 2
    prices.update(bid=Decimal(entry[0]), ask=Decimal(entry[1]))
    assert await runtime.grid.tick(bot.id)
    assert len(adapter.sent) == 3 and abs(adapter.net) == preview.quantity_per_grid
    assert store.grid_state(bot.id)["zero_inventory_cursor"] == 2


async def test_restart_keeps_flat_start_origin_and_does_not_build_a_base_position(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long", open_position_on_start=False)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    prices.update(bid=Decimal("61000.5"), ask=Decimal("61001"))
    reopened = Store(Path(store.engine.url.database))
    resumed = Runtime(reopened, runtime.markets, runtime.accounts)
    try:
        assert not await resumed.grid.tick(bot.id)
        assert reopened.grid_state(bot.id)["zero_inventory_cursor"] == 2
        assert reopened.positions(bot.id) == [] and adapter.sent == []
    finally:
        reopened.close()


@pytest.mark.parametrize("unknown,fraction", [(True, "1"), (False, "0.5")])
async def test_first_trigger_unknown_or_partial_keeps_origin_and_does_not_resend(
    env, monkeypatch, unknown, fraction
):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long", open_position_on_start=False)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    adapter.unknown, adapter.fraction = unknown, Decimal(fraction)
    prices.update(bid=Decimal("58999"), ask=Decimal("58999.5"))
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION and len(adapter.sent) == 1
    assert store.grid_state(bot.id)["zero_inventory_cursor"] == 2
    assert not await runtime.grid.tick(bot.id) and len(adapter.sent) == 1
    if unknown:
        adapter.unknown = False
        await runtime.sync(bot.id)
        assert store.bot(bot.id).state == BotState.PAUSED
        await runtime.command(bot.id, "run")
        assert not await runtime.grid.tick(bot.id) and len(adapter.sent) == 1


async def test_neutral_starts_flat_away_from_interval_midpoint_and_respects_budget(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    prices.update(bid=Decimal("61000.5"), ask=Decimal("61001"))
    bot = grid_bot(store, account)
    preview = await runtime.preview(bot)
    assert preview.zero_inventory_cursor == 3 and preview.initial_quantity == 0
    assert preview.max_notional <= bot.parameters.notional_limit
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id) and adapter.sent == []
    prices.update(bid=Decimal("59999"), ask=Decimal("59999.5"))
    assert await runtime.grid.tick(bot.id) and adapter.net == preview.quantity_per_grid
    prices.update(bid=Decimal("61000.5"), ask=Decimal("61001"))
    assert await runtime.grid.tick(bot.id) and adapter.net == 0


@pytest.mark.parametrize("direction,price", [("long", "58000"), ("short", "62000")])
async def test_no_entry_line_waits_without_orders_or_a_frozen_layout(env, monkeypatch, direction, price):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    prices.update(bid=Decimal(price) - Decimal("0.1"), ask=Decimal(price) + Decimal("0.1"))
    bot = grid_bot(store, account, direction, open_position_on_start=False)
    assert not (await runtime.preview(bot)).can_initialize
    await runtime.command(bot.id, "run")
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.WAITING and store.grid_state(bot.id) is None
    assert adapter.sent == []
    prices.update(bid=Decimal("59999.5"), ask=Decimal("60000.5"))
    assert await runtime.grid.tick(bot.id) and adapter.sent == []
    assert store.grid_state(bot.id)["zero_inventory_cursor"] == 2


async def test_flat_grid_monitor_has_no_sell_plan_until_a_long_position_exists(page, env, monkeypatch):
    store, runtime, account, _ = env
    await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long", open_position_on_start=False)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    runtime.last_tick = time.time()
    with page:
        monitor = GridMonitor()
    monitor.update(store.bot(bot.id), store, await observe_strategy(runtime, store.bot(bot.id)))
    assert monitor.values[1].text == "$59,000.00"
    assert monitor.values[2].text == "暂无卖出"
    assert monitor.rows[3].action.text == "无交易计划" and monitor.rows[3].quantity.text == "—"
    assert "空仓" in monitor.explanation.text


def test_startup_policy_is_required_and_neutral_cannot_request_bulk_entry(env):
    store, _, account, _ = env
    parameters = grid_bot(store, account).parameters.model_dump()
    parameters.pop("open_position_on_start")
    with pytest.raises(ValidationError):
        GridParameters.model_validate(parameters)
    with pytest.raises(ValidationError):
        GridParameters.model_validate({**parameters, "open_position_on_start": True})


async def test_existing_position_blocks_changing_startup_policy(env, monkeypatch):
    store, runtime, account, _ = env
    await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "pause")
    changed = BotUpdate(
        name=bot.name, parameters=bot.parameters.model_copy(update={"open_position_on_start": False})
    )
    with pytest.raises(ValueError):
        store.update_bot(bot.id, changed)


def test_new_form_defaults_to_no_entry_and_explains_seeded_entry(page, env):
    store, runtime, _, _ = env
    with page:
        dialog = grid_dialog(store, runtime, "startup-form", lambda: None)
    direction = next(e for e in page.elements.values() if isinstance(e, ui.toggle))
    switch = next(e for e in page.elements.values() if isinstance(e, ui.switch) and e.text == "启动时建仓")
    assert not switch.value and not switch.visible
    direction.set_value("long")
    assert switch.visible and not switch.value
    switch.set_value(True)
    assert any(isinstance(e, ui.label) and "一次成交多格数量" in e.text for e in page.elements.values())
    direction.set_value("neutral")
    assert not switch.visible and not switch.value
    dialog.delete()
