"""An explicit run after confirmed close starts a new grid, preserving actual history."""

import time
from decimal import Decimal

import pytest
from test_account_form import page as page
from test_grid import grid_bot, grid_market

from perp_farming_bots.bot_widgets import GridBotCard
from perp_farming_bots.models import BotCreate, BotState
from perp_farming_bots.store import fills, operations
from perp_farming_bots.strategy_widgets import observe_strategy


async def test_closed_grid_run_reinitializes_and_preserves_history_and_sync(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    old_cursor = store.grid_state(bot.id)["cursor"]
    await runtime.command(bot.id, "close")
    history = store.rows(fills, bot.id), store.bot_orders(bot.id), store.rows(operations, bot.id)
    turnover = store.turnover(bot.id)
    sent = len(adapter.sent)
    prices.update(bid=Decimal("60999.5"), ask=Decimal("61000.5"))
    await runtime.command(bot.id, "run")
    assert store.bot(bot.id).state == BotState.WAITING
    assert store.grid_state(bot.id) is None and len(adapter.sent) == sent
    assert history == (store.rows(fills, bot.id), store.bot_orders(bot.id), store.rows(operations, bot.id))
    assert store.turnover(bot.id) == turnover
    # A healthy old close must not terminate the new user-authorized run.
    await runtime.sync(bot.id)
    assert store.bot(bot.id).state == BotState.WAITING
    assert await runtime.grid.tick(bot.id)
    assert store.grid_state(bot.id)["cursor"] != old_cursor
    assert adapter.net == Decimal("0.01")
    assert store.bot_orders(bot.id)[0]["operation_id"] != history[1][0]["operation_id"]
    with pytest.raises(ValueError):
        await runtime.command(bot.id, "run")
    assert len(adapter.sent) == sent + 1


async def test_zero_target_grid_can_close_and_run_again_without_fabricating_fills(env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id) and adapter.sent == []
    await runtime.command(bot.id, "close")
    await runtime.command(bot.id, "run")
    assert store.grid_state(bot.id) is None and store.bot(bot.id).state == BotState.WAITING
    assert await runtime.grid.tick(bot.id)
    assert len(store.rows(operations, bot.id)) == 2
    assert store.rows(fills, bot.id) == [] and adapter.sent == []


@pytest.mark.parametrize("blocked", ["stale", "external_order", "reserved", "balance", "pending"])
async def test_failed_closed_grid_preflight_keeps_original_state_and_history(env, monkeypatch, blocked):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "close")
    if blocked == "stale":
        prices["stale"] = True
    elif blocked == "external_order":
        adapter.external_orders = [{"id": "test-only-external"}]
    elif blocked == "reserved":
        other = store.add_bot(
            BotCreate(
                name="other", request_id="test-reuse-reservation", strategy="grid", parameters=bot.parameters
            )
        )
        assert other.id != bot.id
    elif blocked == "balance":
        original = adapter.snapshot

        async def snapshot():
            return (await original()).model_copy(update={"available": Decimal("100")})

        monkeypatch.setattr(adapter, "snapshot", snapshot)
    else:
        store.operation(bot.id, "grid_initial")
    before = store.bot(bot.id), store.grid_state(bot.id), store.rows(operations, bot.id)
    with pytest.raises(ValueError):
        await runtime.command(bot.id, "run")
    assert before == (store.bot(bot.id), store.grid_state(bot.id), store.rows(operations, bot.id))
    assert adapter.sent == []


async def test_closed_grid_with_remaining_allocated_inventory_cannot_reset(env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    store.set_state(bot.id, BotState.CLOSED, "test-only inconsistent state")
    before = store.grid_state(bot.id), store.positions(bot.id), len(adapter.sent)
    with pytest.raises(ValueError):
        await runtime.command(bot.id, "run")
    assert before == (store.grid_state(bot.id), store.positions(bot.id), len(adapter.sent))


async def test_closed_grid_card_offers_explicit_rerun_without_enabling_strategy(page, env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "close")
    runtime.last_tick = time.time()
    with page:
        card = GridBotCard(bot.id, *([lambda *args: None] * 5))
    card.update(store.bot(bot.id), store, await runtime.pnl(bot.id), await runtime.funding(bot.id))
    card.monitor.update(store.bot(bot.id), store, await observe_strategy(runtime, store.bot(bot.id)))
    assert card.buttons["run"].enabled and card.buttons["run"].text == "重新运行"
    assert "重新初始化" in card.monitor.explanation.text
    assert store.bot(bot.id).state == BotState.CLOSED and adapter.sent == []
