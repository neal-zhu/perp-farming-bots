"""An explicit run after confirmed close starts a new grid, preserving actual history."""

import time
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nicegui import ui
from test_account_form import page as page
from test_grid import grid_bot, grid_market

from perp_farming_bots.api import register_routes
from perp_farming_bots.bot_widgets import GridBotCard
from perp_farming_bots.grid_ui import grid_dialog
from perp_farming_bots.models import BotCreate, BotState, BotUpdate, GridMarginCapital
from perp_farming_bots.notifications import Notifications
from perp_farming_bots.store import fills, operations
from perp_farming_bots.strategy_widgets import observe_strategy


@pytest.mark.parametrize("direction", ["long", "neutral"])
async def test_grid_delete_removes_layout_and_preserves_execution_evidence(env, monkeypatch, direction):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, direction)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "close")
    before = store.bot_orders(bot.id), store.rows(fills, bot.id), store.rows(operations, bot.id)
    sent = len(adapter.sent), len(adapter.margin_sent)
    store.delete_bot(bot.id)
    assert store.bots() == [] and store.grid_state(bot.id) is None
    assert (store.bot_orders(bot.id), store.rows(fills, bot.id), store.rows(operations, bot.id)) == before
    assert (len(adapter.sent), len(adapter.margin_sent)) == sent


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


async def test_paused_flat_initialized_grid_can_edit_layout_without_automatically_running(env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "pause")
    assert store.bot_editability(bot.id)["entry_parameters"], (
        "Initialization locked an empty paused grid forever"
    )
    before = (
        store.bot_orders(bot.id),
        store.rows(fills, bot.id),
        store.rows(operations, bot.id),
        store.turnover(bot.id),
    )
    value = BotUpdate(
        name=bot.name,
        parameters=bot.parameters.model_copy(
            update={
                "lower_price": Decimal(59000),
                "upper_price": Decimal(61000),
                "grid_count": 10,
            }
        ),
    )
    await runtime.validate_configuration(value, bot_id=bot.id)
    edited = store.update_bot(bot.id, value)
    assert edited.state == BotState.READY and store.grid_state(bot.id) is None
    assert before == (
        store.bot_orders(bot.id),
        store.rows(fills, bot.id),
        store.rows(operations, bot.id),
        store.turnover(bot.id),
    )
    assert adapter.sent == [] and not await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    assert len(store.grid_state(bot.id)["levels"]) == 11


async def test_closed_grid_can_edit_geometry_with_confirmed_history_but_not_change_binding(env, monkeypatch):
    store, runtime, account, other_account = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "close")
    before = (
        store.bot_orders(bot.id),
        store.rows(fills, bot.id),
        store.rows(operations, bot.id),
        store.turnover(bot.id),
    )
    value = BotUpdate(
        name=bot.name,
        parameters=bot.parameters.model_copy(
            update={
                "direction": "neutral",
                "open_position_on_start": False,
                "lower_price": Decimal(59000),
                "upper_price": Decimal(61000),
                "grid_count": 6,
            }
        ),
    )
    await runtime.validate_configuration(value, bot_id=bot.id)
    edited = store.update_bot(bot.id, value)
    assert edited.state == BotState.CLOSED and store.grid_state(bot.id) is None
    assert before == (
        store.bot_orders(bot.id),
        store.rows(fills, bot.id),
        store.rows(operations, bot.id),
        store.turnover(bot.id),
    )
    changed_account = BotUpdate(
        name=bot.name, parameters=edited.parameters.model_copy(update={"connection_id": other_account.id})
    )
    with pytest.raises(ValueError, match="账户|币种"):
        store.update_bot(bot.id, changed_account)
    assert len(adapter.sent) == 2


@pytest.mark.parametrize("blocked", ["running", "inventory", "pending"])
async def test_grid_layout_edit_rejects_active_inventory_or_unconfirmed_operations(env, monkeypatch, blocked):
    store, runtime, account, _ = env
    await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long" if blocked == "inventory" else "neutral")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    if blocked != "running":
        await runtime.command(bot.id, "pause")
    if blocked == "pending":
        store.operation(bot.id, "grid_step")
    value = BotUpdate(name=bot.name, parameters=bot.parameters.model_copy(update={"grid_count": 6}))
    before = store.bot(bot.id), store.grid_state(bot.id), store.bot_orders(bot.id), store.positions(bot.id)
    with pytest.raises(ValueError):
        await runtime.validate_configuration(value, bot_id=bot.id)
    with pytest.raises(ValueError):
        store.update_bot(bot.id, value)
    assert not store.bot_editability(bot.id)["entry_parameters"]
    assert before == (
        store.bot(bot.id),
        store.grid_state(bot.id),
        store.bot_orders(bot.id),
        store.positions(bot.id),
    )


async def test_paused_empty_grid_api_save_preflight_failure_keeps_original_geometry(env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "pause")
    invalid = BotUpdate(
        name=bot.name,
        parameters=bot.parameters.model_copy(
            update={
                "capital": GridMarginCapital(investment_usd=Decimal(1), leverage=1, margin_mode="cross"),
                "grid_count": 10,
            }
        ),
    )
    before = store.bot(bot.id), store.grid_state(bot.id), store.rows(operations, bot.id)
    app = FastAPI()
    register_routes(app, store, runtime, Notifications(store, runtime.accounts.secrets))
    with TestClient(app) as client:
        response = client.put(f"/api/bots/{bot.id}", json=invalid.model_dump(mode="json"))
    assert response.status_code == 400 and "至少" in response.text
    assert before == (store.bot(bot.id), store.grid_state(bot.id), store.rows(operations, bot.id))
    assert adapter.sent == [] and adapter.margin_sent == []


async def test_empty_paused_grid_form_unlocks_geometry_and_capital(page, env, monkeypatch):
    store, runtime, account, _ = env
    await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "pause")
    with page:
        dialog = grid_dialog(store, runtime, "paused-grid-edit", lambda: None, bot_id=bot.id)
    for label in ["价格下限（USD）", "价格上限（USD）", "网格数", "投入保证金额度（USD）", "杠杆倍数"]:
        field = next(e for e in page.elements.values() if isinstance(e, ui.number) and e.label == label)
        assert field.enabled
    dialog.delete()


async def test_binding_change_checks_original_native_inventory_before_discarding_empty_grid(env, monkeypatch):
    store, runtime, account, new_account = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "pause")
    adapter.net = Decimal("0.005")  # Unallocated external native inventory.
    value = BotUpdate(
        name=bot.name, parameters=bot.parameters.model_copy(update={"connection_id": new_account.id})
    )
    before = store.bot(bot.id), store.grid_state(bot.id)
    with pytest.raises(ValueError, match="实际持仓"):
        await runtime.validate_configuration(value, bot_id=bot.id)
    assert before == (store.bot(bot.id), store.grid_state(bot.id))
