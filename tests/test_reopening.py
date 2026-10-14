from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from nicegui import ui
from pydantic import ValidationError
from sqlalchemy import update
from test_account_form import click
from test_account_form import page as page
from test_bot_management import bot_page as bot_page
from test_bot_management import configured_bot as configured_bot
from test_runtime import make_bot, open_bot

from perp_farming_bots import runtime as runtime_module
from perp_farming_bots.models import BotState, BotUpdate, HedgeParameters, OrderResult
from perp_farming_bots.store import Store, fills


def configure(store, bot, **parameters):
    return store.update_bot(
        bot.id,
        BotUpdate(
            name=bot.name,
            parameters=HedgeParameters.model_validate({**bot.parameters.model_dump(), **parameters}),
        ),
    )


@pytest.fixture
def clock(monkeypatch):
    now = [1791800000.0]
    monkeypatch.setattr(runtime_module.time, "time", lambda: now[0])
    return now


async def test_reopening_waits_for_interval_random_delay_and_spread_and_counts_all_cycles(
    env, clock, monkeypatch
):
    store, runtime, a, b = env
    bot = make_bot(store, a, b, amount="120.002")
    configure(store, bot, reopen_interval_seconds=60, reopen_random_wait_seconds=120)
    await runtime.command(bot.id, "run")
    assert await runtime.try_open(bot.id)
    assert store.turnover(bot.id) == {"confirmed_usd": "240.000", "has_unconfirmed_orders": False}
    other = await open_bot(store, runtime, a, b, request="second-bot", amount="120.002")
    other_inventory = store.positions(other.id)
    assert not await runtime.try_reopen(bot.id)
    clock[0] += 60
    monkeypatch.setattr(runtime_module.secrets, "randbelow", lambda bound: 90)
    assert await runtime.try_reopen(bot.id)
    assert store.bot(bot.id).state == BotState.WAITING
    assert store.positions(bot.id) == []
    assert store.positions(other.id) == other_inventory
    saved_cycle = store.cycle(bot.id)
    await runtime.sync(bot.id)
    assert store.bot(bot.id).state == BotState.WAITING
    assert store.cycle(bot.id) == saved_cycle, "sync of completed journals must not end an active wait"
    assert store.turnover(bot.id)["confirmed_usd"] == "480.000"
    assert store.cycle(bot.id)["number"] == 2
    assert store.cycle(bot.id)["entry_not_before"] == clock[0] + 90
    assert not await runtime.try_open(bot.id)
    assert not await runtime.try_reopen(bot.id)
    clock[0] += 90
    actual_preview = runtime.preview
    preview = await actual_preview(store.bot(bot.id))
    monkeypatch.setattr(
        runtime, "preview", AsyncMock(return_value=preview.model_copy(update={"spread_pct": Decimal("-1")}))
    )
    assert not await runtime.try_open(bot.id), "random delay ending must not bypass spread condition"
    assert store.positions(bot.id) == []
    monkeypatch.setattr(runtime, "preview", actual_preview)
    assert await runtime.try_open(bot.id)
    assert store.turnover(bot.id)["confirmed_usd"] == "720.000"
    assert not await runtime.try_open(bot.id), "same cycle cannot submit entry twice"
    assert store.cycle(bot.id)["next_reopen_at"] == clock[0] + 60
    assert store.positions(other.id) == other_inventory


async def test_pause_resume_restarts_timer_and_manual_close_ends_reopening(env, clock):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    configure(store, bot, reopen_interval_seconds=60)
    clock[0] += 30
    await runtime.command(bot.id, "pause")
    assert store.cycle(bot.id)["next_reopen_at"] is None
    clock[0] += 1000
    assert not await runtime.try_reopen(bot.id)
    await runtime.command(bot.id, "run")
    assert store.cycle(bot.id)["next_reopen_at"] == clock[0] + 60
    assert not await runtime.try_reopen(bot.id)
    await runtime.command(bot.id, "close")
    clock[0] += 1000
    assert store.bot(bot.id).state == BotState.CLOSED
    assert store.cycle(bot.id)["next_reopen_at"] is None
    assert not await runtime.try_reopen(bot.id)
    assert not await runtime.try_open(bot.id)
    assert len(runtime.accounts.adapter(a.id).sent) == 2


@pytest.mark.parametrize("failure", ["partial", "unknown", "unknown-peer", "inventory"])
async def test_failed_reopen_close_stops_without_reentry_or_automatic_retry(env, clock, failure, monkeypatch):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b, amount="120.002")
    configure(store, bot, reopen_interval_seconds=60, reopen_random_wait_seconds=0)
    if failure == "partial":
        runtime.accounts.adapter(a.id).fraction = Decimal("0.5")
    elif failure in {"unknown", "unknown-peer"}:
        runtime.accounts.adapter(a.id if failure == "unknown" else b.id).unknown = True
        original_sleep = runtime_module.asyncio.sleep

        async def fast_sleep(delay):
            await original_sleep(0)

        monkeypatch.setattr(runtime_module.asyncio, "sleep", fast_sleep)
    else:
        runtime.accounts.adapter(a.id).net += Decimal("0.01")
    clock[0] += 60
    assert not await runtime.try_reopen(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION
    assert store.cycle(bot.id)["number"] == 1
    assert store.cycle(bot.id)["next_reopen_at"] is None
    sends = [len(runtime.accounts.adapter(c.id).sent) for c in [a, b]]
    if failure in {"unknown", "unknown-peer"}:
        runtime.accounts.adapter(a.id if failure == "unknown" else b.id).unknown = False
    await runtime.sync(bot.id)
    if failure == "unknown-peer":
        assert store.bot(bot.id).state == BotState.CLOSED
        assert store.positions(bot.id) == []
    assert not await runtime.try_reopen(bot.id)
    assert not await runtime.try_open(bot.id)
    assert [len(runtime.accounts.adapter(c.id).sent) for c in [a, b]] == sends


async def test_random_deadline_and_volume_survive_store_restart_and_pause_between_cycles(
    env, clock, monkeypatch
):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    configure(store, bot, reopen_interval_seconds=60, reopen_random_wait_seconds=300)
    monkeypatch.setattr(runtime_module.secrets, "randbelow", lambda bound: 300)
    clock[0] += 60
    assert await runtime.try_reopen(bot.id)
    cycle = store.cycle(bot.id)
    path = Path(store.engine.url.database)
    reopened = Store(path)
    try:
        assert reopened.cycle(bot.id) == cycle
        assert reopened.turnover(bot.id) == store.turnover(bot.id)
    finally:
        reopened.close()
    await runtime.command(bot.id, "pause")
    clock[0] += 300
    assert not await runtime.try_open(bot.id)
    await runtime.command(bot.id, "run")
    assert await runtime.try_open(bot.id), "completed old-cycle orders must not block a new cycle"


async def test_manual_close_ends_flat_random_wait_without_new_order(env, clock, monkeypatch):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    configure(store, bot, reopen_interval_seconds=60)
    monkeypatch.setattr(runtime_module.secrets, "randbelow", lambda bound: 300)
    clock[0] += 60
    assert await runtime.try_reopen(bot.id)
    await runtime.command(bot.id, "close")
    assert store.bot(bot.id).state == BotState.CLOSED
    clock[0] += 300
    assert not await runtime.try_open(bot.id)
    assert len(runtime.accounts.adapter(a.id).sent) == len(runtime.accounts.adapter(b.id).sent) == 2


async def test_late_fee_enrichment_of_old_cycle_does_not_change_new_inventory_or_turnover(env, clock):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    first_order = next(o for o in store.bot_orders(bot.id) if o["role"] == "long")
    # Independently remove a fee, representing an earlier confirmed fill with unknown fee.
    import json

    from perp_farming_bots.store import orders

    previous = OrderResult.model_validate(first_order["result"])
    with store.transaction() as db:
        db.execute(
            update(orders)
            .where(orders.c.id == first_order["id"])
            .values(result=json.dumps({**first_order["result"], "fee": None}))
        )
        db.execute(update(fills).where(fills.c.id == first_order["id"]).values(fee=None))
    configure(store, bot, reopen_interval_seconds=60, reopen_random_wait_seconds=0)
    clock[0] += 60
    assert await runtime.try_reopen(bot.id)
    assert await runtime.try_open(bot.id)
    current = store.positions(bot.id)
    volume = store.turnover(bot.id)
    store.apply_order_result(first_order["id"], previous.model_copy(update={"fee": Decimal("2")}))
    assert store.positions(bot.id) == current
    assert store.turnover(bot.id) == volume


@pytest.mark.parametrize(
    "changes",
    [
        {"reopen_interval_seconds": 0},
        {"reopen_interval_seconds": 59},
        {"reopen_random_wait_seconds": 301},
        {"reopen_random_wait_seconds": -1},
    ],
)
def test_invalid_reopening_parameters_are_rejected(changes):
    with pytest.raises(ValidationError):
        HedgeParameters(
            long_connection_id="a",
            short_connection_id="b",
            long_symbol="BTC", short_symbol="BTC",
            threshold_pct=0,
            target_usd=100,
            **changes,
        )


async def test_reopen_form_validates_random_max_and_persists_seconds(bot_page, configured_bot, env):
    import asyncio

    store, _, _, _ = env
    click(bot_page, "修改参数")
    switch = next(e for e in bot_page.elements.values() if isinstance(e, ui.switch) and e.text == "定期重开")
    interval = next(
        e for e in bot_page.elements.values() if isinstance(e, ui.number) and e.label == "持仓间隔（分钟）"
    )
    wait = next(
        e
        for e in bot_page.elements.values()
        if isinstance(e, ui.number) and e.label == "随机等待上限（分钟）"
    )
    switch.set_value(True)
    interval.set_value(30)
    wait.set_value(6)
    await asyncio.gather(*click(bot_page, "保存 Bot"))
    assert wait.error == "随机等待须为 0–5 分钟"
    assert store.bot(configured_bot.id).parameters.reopen_interval_seconds is None
    wait.set_value(2.5)
    await asyncio.gather(*click(bot_page, "保存 Bot"))
    saved = store.bot(configured_bot.id)
    assert saved.parameters.reopen_interval_seconds == 1800
    assert saved.parameters.reopen_random_wait_seconds == 150
