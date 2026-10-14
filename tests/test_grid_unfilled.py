"""A confirmed unfilled IOC leaves the grid ready for a fresh price trigger."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr
from test_grid import grid_bot, grid_market

from perp_farming_bots.models import BotState, ConnectionCreate, OrderIntent, Provider
from perp_farming_bots.runtime import Runtime
from perp_farming_bots.store import Store, alerts, operations
from perp_farming_bots.trading import Arcus


@pytest.mark.parametrize("reduce", [False, True])
async def test_unfilled_step_preserves_grid_and_waits_for_new_order(env, monkeypatch, reduce):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long", open_position_on_start=False)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    entry = {"bid": Decimal("58999"), "ask": Decimal("58999.5")}
    exit_price = {"bid": Decimal("60000.5"), "ask": Decimal("60001")}
    if reduce:
        prices.update(entry)
        assert await runtime.grid.tick(bot.id)
    before = store.grid_state(bot.id), store.positions(bot.id)
    prices.update(exit_price if reduce else entry)
    adapter.fraction = Decimal(0)
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.HOLDING, "Zero-fill IOC cancellation stopped the grid"
    assert (store.grid_state(bot.id), store.positions(bot.id)) == before
    canceled = store.bot_orders(bot.id)[0]
    assert canceled["status"] == "canceled" and canceled["applied"]
    assert store.rows(operations, bot.id)[0]["status"] == "skipped"
    assert not store.bot_pending(bot.id) and store.rows(alerts, bot.id) == []
    sent = len(adapter.sent)
    adapter.fraction = Decimal(1)
    prices.update(entry if reduce else exit_price)
    assert not await runtime.grid.tick(bot.id) and len(adapter.sent) == sent
    prices.update(exit_price if reduce else entry)
    assert await runtime.grid.tick(bot.id)
    assert len(adapter.sent) == sent + 1
    assert adapter.sent[-1].client_id != canceled["intent"]["client_id"]
    assert adapter.sent[-1].reduce_only == reduce
    assert store.bot_orders(bot.id)[1] == canceled


async def test_unfilled_initial_order_keeps_journal_and_can_initialize_again(env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    adapter.fraction = Decimal(0)
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.WAITING
    assert store.grid_state(bot.id) is None and store.positions(bot.id) == []
    canceled = store.bot_orders(bot.id)[0]
    assert canceled["applied"] and not store.bot_pending(bot.id)
    adapter.fraction = Decimal(1)
    assert await runtime.grid.tick(bot.id)
    assert len(adapter.sent) == 2 and adapter.sent[0].client_id != adapter.sent[1].client_id
    assert store.bot_orders(bot.id)[1] == canceled
    assert store.grid_state(bot.id)["initialized"]


async def test_restart_after_unfilled_ioc_preserves_layout_and_never_replays(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long", open_position_on_start=False)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    original = store.grid_state(bot.id)
    adapter.fraction = Decimal(0)
    prices.update(bid=Decimal("58999"), ask=Decimal("58999.5"))
    assert not await runtime.grid.tick(bot.id)
    reopened = Store(Path(store.engine.url.database))
    resumed = Runtime(reopened, runtime.markets, runtime.accounts)
    try:
        adapter.fraction = Decimal(1)
        prices.update(bid=Decimal("59999.5"), ask=Decimal("60000.5"))
        assert not await resumed.grid.tick(bot.id)
        assert reopened.grid_state(bot.id) == original and len(adapter.sent) == 1
    finally:
        reopened.close()


async def test_non_cancel_rejection_with_zero_fills_still_pauses(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long", open_position_on_start=False)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    original = store.grid_state(bot.id)
    adapter.fraction = Decimal(0)
    send = adapter.send

    async def reject(prepared):
        native_id = await send(prepared)
        adapter.results[adapter.sent[-1].client_id].status = "rejected"
        return native_id

    monkeypatch.setattr(adapter, "send", reject)
    prices.update(bid=Decimal("58999"), ask=Decimal("58999.5"))
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION
    assert "交易所拒绝" in store.bot(bot.id).reason and "平仓" not in store.bot(bot.id).reason
    assert store.grid_state(bot.id) == original
    assert not await runtime.grid.tick(bot.id) and len(adapter.sent) == 1


async def test_unknown_then_confirmed_zero_only_syncs_and_waits_for_manual_run(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long", open_position_on_start=False)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    original = store.grid_state(bot.id)
    adapter.fraction, adapter.unknown = Decimal(0), True
    prices.update(bid=Decimal("58999"), ask=Decimal("58999.5"))
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION and store.bot_pending(bot.id)
    adapter.unknown = False
    await runtime.sync(bot.id)
    assert store.bot(bot.id).state == BotState.PAUSED
    assert store.grid_state(bot.id) == original and not store.bot_pending(bot.id)
    assert len(adapter.sent) == 1 and not await runtime.grid.tick(bot.id)
    adapter.fraction = Decimal(1)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id) and len(adapter.sent) == 2


@pytest.mark.parametrize(
    "reason,expected", [("IOC_CANCELED", "canceled"), ("INSUFFICIENT_MARGIN", "rejected"), (None, "rejected")]
)
async def test_arcus_explicit_ioc_cancel_is_normalized_without_hiding_other_rejections(
    env, monkeypatch, reason, expected
):
    _, runtime, account, _ = env
    adapter = Arcus(
        ConnectionCreate(
            name="arcus",
            provider=Provider.ARCUS,
            address="0x" + "1" * 40,
            account_index=0,
            api_private_key=SecretStr("2" * 64),
        ),
        runtime.markets,
    )
    intent = OrderIntent(
        connection_id=account.id,
        symbol="BTC",
        side="buy",
        quantity="0.001",
        limit_price="59000",
        reduce_only=False,
        client_id="original-client",
    )

    async def original(path, **params):
        assert path == "/v1/order/original-native"
        return {
            "orderId": "original-native",
            "clientId": intent.client_id,
            "marketId": 1,
            "side": "BUY",
            "originalSize": "0.001",
            "remainingSize": "0.001",
            "status": "REJECTED",
            "timeInForce": "IOC",
            "rejectionReason": reason,
        }

    monkeypatch.setattr(adapter, "get", original)
    result = await adapter.lookup(intent, "original-native")
    assert result.status == expected and result.quantity == 0
