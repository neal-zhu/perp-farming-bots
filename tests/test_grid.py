"""Test-only books/adapters exercise live strategy logic without contacting a venue."""

import asyncio
import json
import time
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from pydantic import ValidationError
from test_account_form import click
from test_account_form import page as page
from test_runtime import make_bot

from perp_farming_bots.grid import GridPreview
from perp_farming_bots.models import Book, BotCreate, BotState, BotUpdate, GridParameters, Level
from perp_farming_bots.runtime import Runtime
from perp_farming_bots.store import Store, fills, orders


def grid_bot(store, account, direction="neutral", **changes):
    params = dict(
        connection_id=account.id,
        symbol="BTC",
        direction=direction,
        lower_price="58000",
        upper_price="62000",
        grid_count=4,
        capital={"investment_usd": "1240", "leverage": 2, "margin_mode": "cross"},
    )
    params.update(changes)
    return store.add_bot(
        BotCreate(
            name="grid",
            request_id="grid-" + account.id + params["symbol"],
            strategy="grid",
            parameters=GridParameters(**params),
        )
    )


async def grid_market(runtime, account, monkeypatch):
    prices = {"bid": Decimal("59999.5"), "ask": Decimal("60000.5"), "stale": False}

    async def book(provider, symbol, *, refresh=False):
        return Book(
            provider=provider,
            symbol=symbol,
            bids=[Level(price=prices["bid"], quantity="10")],
            asks=[Level(price=prices["ask"], quantity="10")],
            received_at=time.time() - (60 if prices["stale"] else 0),
            source="test-only book",
        )

    monkeypatch.setattr(runtime.markets, "book", book)
    adapter = runtime.accounts.adapter(account.id)
    original_send = adapter.send

    async def send(payload):
        native = await original_send(payload)
        intent = adapter.sent[-1]
        result = adapter.results[intent.client_id]
        result.average_price = prices["ask" if intent.side == "buy" else "bid"] if result.quantity else None
        result.fee = Decimal("0.1") if result.quantity else Decimal(0)
        return native

    monkeypatch.setattr(adapter, "send", send)
    return prices, adapter


@pytest.mark.parametrize(
    "direction,initial,entry_bid,entry_ask,exit_bid,exit_ask,side",
    [
        ("long", Decimal("0.02"), "58999", "58999.5", "60000.5", "60001", "buy"),
        ("short", Decimal("-0.02"), "61000.5", "61001", "59999", "59999.5", "sell"),
    ],
)
async def test_directional_grid_accumulates_and_reduces_confirmed_inventory(
    env, monkeypatch, direction, initial, entry_bid, entry_ask, exit_bid, exit_ask, side
):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, direction)
    preview = await runtime.preview(bot)
    assert isinstance(preview, GridPreview)
    assert preview.initial_quantity == initial and preview.max_notional <= bot.parameters.notional_limit
    await runtime.command(bot.id, "run")
    assert adapter.sent == []  # User command enables strategy; sends occur in its tick.
    assert await runtime.grid.tick(bot.id)
    assert adapter.net == initial
    prices.update(bid=Decimal(entry_bid), ask=Decimal(entry_ask))
    assert await runtime.grid.tick(bot.id)
    assert adapter.sent[-1].side == side and not adapter.sent[-1].reduce_only
    assert abs(adapter.net) == Decimal("0.03")
    prices.update(bid=Decimal(exit_bid), ask=Decimal(exit_ask))
    assert await runtime.grid.tick(bot.id)
    assert adapter.sent[-1].reduce_only and adapter.net == initial
    assert len(store.rows(fills, bot.id)) == 3
    await runtime.accounts.refresh(account.id)
    pnl = await runtime.pnl(bot.id)
    assert Decimal(pnl["realized"]) > 0 and pnl["fees"] == "0.3"
    expected = sum(
        (Decimal(f["quantity"]) * Decimal(f["price"]) for f in store.rows(fills, bot.id)), Decimal(0)
    )
    assert Decimal(store.turnover(bot.id)["confirmed_usd"]) == expected
    assert not await runtime.grid.tick(bot.id)
    assert len(adapter.sent) == 3  # No repeat at the same level.


async def test_neutral_grid_flattens_at_center_before_switching_direction(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    assert store.grid_state(bot.id)["cursor"] == 2 and adapter.sent == []
    for bid, ask, expected, reduce in [
        ("58999", "58999.5", "0.02", False),
        ("60000.5", "60001", "0", True),
        ("61000.5", "61001", "-0.02", False),
        ("59999", "59999.5", "0", True),
    ]:
        prices.update(bid=Decimal(bid), ask=Decimal(ask))
        assert await runtime.grid.tick(bot.id)
        assert adapter.net == Decimal(expected) and adapter.sent[-1].reduce_only == reduce
        assert len(store.positions(bot.id)) <= 1
    assert len(adapter.sent) == 4
    assert store.bot_editability(bot.id)["entry_parameters"] is False
    assert Decimal((await runtime.pnl(bot.id))["realized"]) > 0


async def test_outside_range_and_pause_preserve_inventory_and_cursor(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    state, positions = store.grid_state(bot.id), store.positions(bot.id)
    prices.update(bid=Decimal("57000"), ask=Decimal("57001"))
    assert not await runtime.grid.tick(bot.id)
    assert store.positions(bot.id) == positions and store.grid_state(bot.id) == state
    await runtime.command(bot.id, "pause")
    prices.update(bid=Decimal("58999"), ask=Decimal("58999.5"))
    assert not await runtime.grid.tick(bot.id)
    await runtime.command(bot.id, "run")
    assert store.grid_state(bot.id) == state
    assert await runtime.grid.tick(bot.id)
    assert len(adapter.sent) == 2
    await runtime.command(bot.id, "close")
    assert adapter.sent[-1].reduce_only and adapter.net == 0
    assert store.positions(bot.id) == [] and store.bot(bot.id).state == BotState.CLOSED
    assert not await runtime.grid.tick(bot.id)


async def test_initial_entry_waits_for_range_without_any_order(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    prices.update(bid=Decimal("57000"), ask=Decimal("57001"))
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert not await runtime.grid.tick(bot.id)
    assert store.grid_state(bot.id) is None and adapter.sent == []
    await runtime.command(bot.id, "close")
    assert store.bot(bot.id).state == BotState.CLOSED


@pytest.mark.parametrize("unknown,fraction", [(False, "0.5"), (False, "0"), (True, "1")])
async def test_unconfirmed_or_partial_grid_never_repeats_submission(env, monkeypatch, unknown, fraction):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    adapter.unknown, adapter.fraction = unknown, Decimal(fraction)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION
    assert not await runtime.grid.tick(bot.id) and len(adapter.sent) == 1
    assert store.grid_state(bot.id)["initialized"] is False
    if unknown:
        assert (await runtime.pnl(bot.id))["net"] is None
        assert store.turnover(bot.id)["has_unconfirmed_orders"]
        adapter.unknown = False
        await runtime.sync(bot.id)
        assert store.bot(bot.id).state == BotState.PAUSED
        assert store.grid_state(bot.id)["initialized"] is True
        await runtime.command(bot.id, "run")
        assert not await runtime.grid.tick(bot.id) and len(adapter.sent) == 1
    else:
        assert sum((p.quantity for p in store.positions(bot.id)), Decimal(0)) == Decimal("0.02") * Decimal(
            fraction
        )
        await runtime.command(bot.id, "pause")
        with pytest.raises(ValueError, match="不会补单"):
            await runtime.command(bot.id, "run")
        adapter.fraction = Decimal(1)
        await runtime.command(bot.id, "close")
        assert store.bot(bot.id).state == BotState.CLOSED


async def test_grid_owns_account_symbol_and_cannot_mix_with_another_bot(env):
    store, _, a, b = env
    grid_bot(store, a)
    with pytest.raises(ValueError, match="独占"):
        make_bot(store, a, b)
    with pytest.raises(ValueError, match="独占"):
        store.add_bot(
            BotCreate(
                name="other",
                request_id="different-grid-id",
                strategy="grid",
                parameters=GridParameters(
                    connection_id=a.id,
                    symbol="BTC",
                    direction="short",
                    lower_price=58000,
                    upper_price=62000,
                    grid_count=4,
                    capital={"investment_usd": 1000, "leverage": 1, "margin_mode": "cross"},
                ),
            )
        )
    # Different native account, same venue is allowed.
    grid_bot(store, b, symbol="ETH")


@pytest.mark.parametrize("external", ["position", "order", "stale"])
async def test_external_inventory_orders_and_stale_quotes_block_grid(env, monkeypatch, external):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    if external == "position":
        adapter.net = Decimal("0.001")
    elif external == "order":
        adapter.external_orders = [{"id": "manual"}]
    else:
        prices["stale"] = True
    with pytest.raises(ValueError):
        await runtime.command(bot.id, "run")
    assert adapter.sent == []


async def test_restart_preserves_grid_geometry_and_never_replays_healthy_initialization(env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    saved = store.grid_state(bot.id)
    reopened = Store(Path(store.engine.url.database))
    resumed = Runtime(reopened, runtime.markets, runtime.accounts)
    try:
        assert reopened.grid_state(bot.id) == saved
        assert not await resumed.grid.tick(bot.id)
        assert len(adapter.sent) == 1
        assert reopened.positions(bot.id) == store.positions(bot.id)
    finally:
        reopened.close()


async def test_partial_close_leaves_only_owned_remainder_and_can_be_closed_again(env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    adapter.fraction = Decimal("0.5")
    await runtime.command(bot.id, "close")
    assert store.bot(bot.id).state == BotState.ATTENTION
    assert adapter.net == Decimal("0.01")
    adapter.fraction = Decimal(1)
    await runtime.command(bot.id, "close")
    assert adapter.sent[-1].quantity == Decimal("0.01") and adapter.sent[-1].reduce_only
    assert store.bot(bot.id).state == BotState.CLOSED and adapter.net == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"grid_count": 3},
        {"lower_price": 62000},
        {"grid_count": 4.5},
        {"capital": {"investment_usd": "NaN", "leverage": 1, "margin_mode": "cross"}},
    ],
)
async def test_invalid_grid_parameters_are_rejected_explicitly(env, changes):
    store, _, account, _ = env
    with pytest.raises(ValidationError):
        grid_bot(store, account, **changes)


async def test_cannot_change_strategy_or_locked_geometry(env, monkeypatch):
    store, runtime, account, _ = env
    await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)  # Even flat neutral initialization locks persisted geometry.
    changed = bot.parameters.model_copy(update={"grid_count": 8})
    with pytest.raises(ValueError):
        store.update_bot(bot.id, BotUpdate(name="changed", parameters=changed))
    edited = store.update_bot(
        bot.id,
        BotUpdate(
            name="renamed", parameters=bot.parameters.model_copy(update={"slippage_bps": Decimal("30")})
        ),
    )
    assert edited.name == "renamed" and store.grid_state(bot.id)["cursor"] == 2


async def test_persisted_grid_order_remains_ioc_and_clamped_to_signal_price(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    prices.update(bid=Decimal("58999"), ask=Decimal("58999.5"))
    assert await runtime.grid.tick(bot.id)
    assert adapter.sent[-1].limit_price <= Decimal("59000")
    row = store.rows(orders, bot.id)[0]
    assert row["applied"] == 1 and json.loads(row["intent"])["reduce_only"] is False


async def test_confirmed_fill_with_interrupted_cursor_commit_recovers_paused_without_resend(env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    complete = store.complete_grid_action

    def interrupted(*args, **kwargs):
        raise RuntimeError("test-only crash after confirmed fill")

    monkeypatch.setattr(store, "complete_grid_action", interrupted)
    await runtime.command(bot.id, "run")
    assert not await runtime.grid.tick(bot.id)
    assert len(adapter.sent) == 1 and len(store.rows(fills, bot.id)) == 1
    monkeypatch.setattr(store, "complete_grid_action", complete)
    await runtime.sync(bot.id)
    assert store.bot(bot.id).state == BotState.PAUSED
    assert store.grid_state(bot.id)["initialized"]
    await runtime.sync(bot.id)
    assert len(adapter.sent) == 1 and len(store.rows(fills, bot.id)) == 1


async def test_last_quote_leaving_range_blocks_initial_order(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    original = runtime._execute

    async def execute(*args, **kwargs):
        prices.update(bid=Decimal("57000"), ask=Decimal("57001"))
        return await original(*args, **kwargs)

    monkeypatch.setattr(runtime, "_execute", execute)
    await runtime.command(bot.id, "run")
    assert not await runtime.grid.tick(bot.id)
    assert adapter.sent == [] and store.bot_orders(bot.id) == []
    assert store.bot(bot.id).state == BotState.ATTENTION


async def test_actual_grid_create_form_validates_inline_and_saves_without_orders(page, env):
    store, runtime, account, other = env
    store.delete_connection(other.id)  # A grid needs only one account.
    click(page, "创建 Bot")
    label = next(
        e
        for e in page.elements.values()
        if isinstance(e, ui.label)
        and e.text == "永续网格"
        and e.parent_slot.parent
        in [
            b.parent_slot.parent
            for b in page.elements.values()
            if isinstance(b, ui.button) and b.text == "选择此策略"
        ]
    )
    button = next(e for e in label.parent_slot.parent.default_slot.children if isinstance(e, ui.button))
    listener = next(e for e in button._event_listeners.values() if e.type == "click")
    page.handle_event({"id": button.id, "listener_id": listener.id, "args": []})
    name = next(e for e in page.elements.values() if isinstance(e, ui.input) and e.label == "Bot 名称 *")
    for e in page.elements.values():
        if isinstance(e, ui.number) and e.label == "价格下限（USD）":
            e.set_value(58000)
        elif isinstance(e, ui.number) and e.label == "价格上限（USD）":
            e.set_value(62000)
        elif isinstance(e, ui.number) and e.label == "投入保证金额度（USD）":
            e.set_value(1000)
    name.set_value("")
    await asyncio.gather(*click(page, "保存 Bot"))
    assert name.error == "请输入 Bot 名称" and store.bots() == []
    name.set_value("我的中性网格")
    await asyncio.gather(*click(page, "保存 Bot"))
    bot = store.bots()[0]
    assert bot.strategy == "grid" and bot.parameters.direction == "neutral" and bot.state == BotState.READY
    assert runtime.accounts.adapter(account.id).sent == []
    labels = [e.text for e in page.elements.values() if isinstance(e, ui.label)]
    assert any("中性网格" in s for s in labels)
    assert "当前只有一条腿有已确认持仓，请先核实订单。" not in labels
    before = set(page.elements)
    with page:
        await page.test_refresh()
    assert set(page.elements) == before
