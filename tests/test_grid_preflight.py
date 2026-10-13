"""Check parameter submission itself, without enabling strategy execution."""

import asyncio
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nicegui import ui
from test_account_form import click
from test_account_form import page as page
from test_grid import grid_bot

from perp_farming_bots.api import register_routes
from perp_farming_bots.grid_ui import grid_dialog
from perp_farming_bots.models import BotCreate, BotUpdate, GridParameters
from perp_farming_bots.notifications import Notifications


async def test_grid_api_rejects_below_minimum_budget_before_saving(env):
    store, runtime, account, _ = env
    value = BotCreate(
        name="too small",
        request_id="grid-minimum-submit",
        strategy="grid",
        parameters=GridParameters(
            connection_id=account.id,
            symbol="BTC",
            direction="neutral",
            lower_price=58000,
            upper_price=62000,
            grid_count=4,
            budget_usd=10,
        ),
    )
    app = FastAPI()
    register_routes(app, store, runtime, Notifications(store, runtime.accounts.secrets))
    with TestClient(app) as client:
        response = client.post("/api/bots", json=value.model_dump(mode="json"))
    assert response.status_code == 400, "Invalid grid was saved; the minimum check happens only at run"
    assert store.bots() == []
    assert runtime.accounts.adapter(account.id).sent == []


@pytest.mark.parametrize("unavailable", [False, True])
async def test_grid_api_rejects_insufficient_or_unknown_balance_before_save(env, monkeypatch, unavailable):
    store, runtime, account, _ = env
    adapter = runtime.accounts.adapter(account.id)
    original = adapter.snapshot

    async def snapshot():
        if unavailable:
            raise ValueError("balance unavailable")
        return (await original()).model_copy(update={"available": Decimal("100")})

    monkeypatch.setattr(adapter, "snapshot", snapshot)
    value = BotCreate(
        name="funds",
        request_id="grid-funds-save",
        strategy="grid",
        parameters=GridParameters(
            connection_id=account.id,
            symbol="BTC",
            direction="neutral",
            lower_price=58000,
            upper_price=62000,
            grid_count=4,
            budget_usd=500,
        ),
    )
    app = FastAPI()
    register_routes(app, store, runtime, Notifications(store, runtime.accounts.secrets))
    with TestClient(app) as client:
        response = client.post("/api/bots", json=value.model_dump(mode="json"))
    assert response.status_code == 400 and store.bots() == []
    assert (
        "balance unavailable" in response.text
        if unavailable
        else "$100.00" in response.text and "$500.00" in response.text
    )
    assert adapter.sent == []


async def test_grid_edit_preflight_excludes_own_reservation_and_blocks_invalid_budget(env):
    store, runtime, account, _ = env
    bot = grid_bot(store, account)
    app = FastAPI()
    register_routes(app, store, runtime, Notifications(store, runtime.accounts.secrets))
    invalid = BotUpdate(
        name=bot.name, parameters=bot.parameters.model_copy(update={"budget_usd": Decimal("10")})
    )
    with TestClient(app) as client:
        failed = client.put(f"/api/bots/{bot.id}", json=invalid.model_dump(mode="json"))
        assert failed.status_code == 400 and "$124.00" in failed.text
        assert store.bot(bot.id).parameters == bot.parameters
        valid = BotUpdate(
            name=bot.name, parameters=bot.parameters.model_copy(update={"budget_usd": Decimal("124")})
        )
        result = client.post(f"/api/bots/{bot.id}/preview", json=valid.model_dump(mode="json"))
        assert result.status_code == 200
        assert result.json()["minimum_budget"] == "124.000"
        assert result.json()["quantity_per_grid"] == "0.001"
        assert result.json()["account_available"] == "10000"
        assert client.put(f"/api/bots/{bot.id}", json=valid.model_dump(mode="json")).status_code == 200
    assert runtime.accounts.adapter(account.id).sent == []


async def test_holding_grid_name_and_slippage_edit_does_not_require_budget_again(env, monkeypatch):
    store, runtime, account, _ = env
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    adapter = runtime.accounts.adapter(account.id)
    original = adapter.snapshot

    async def snapshot():
        return (await original()).model_copy(update={"available": Decimal("10")})

    monkeypatch.setattr(adapter, "snapshot", snapshot)
    before = store.positions(bot.id), store.grid_state(bot.id), len(adapter.sent)
    value = BotUpdate(
        name="renamed", parameters=bot.parameters.model_copy(update={"slippage_bps": Decimal("30")})
    )
    app = FastAPI()
    register_routes(app, store, runtime, Notifications(store, runtime.accounts.secrets))
    with TestClient(app) as client:
        assert client.put(f"/api/bots/{bot.id}", json=value.model_dump(mode="json")).status_code == 200
    assert (store.positions(bot.id), store.grid_state(bot.id), len(adapter.sent)) == before


async def test_currency_switch_clears_old_price_range(page, env):
    store, runtime, _, _ = env

    async def saved():
        pass

    with page:
        dialog = grid_dialog(store, runtime, "new-currency-grid", saved)
    lower = next(
        e for e in page.elements.values() if isinstance(e, ui.number) and e.label == "价格下限（USD）"
    )
    upper = next(
        e for e in page.elements.values() if isinstance(e, ui.number) and e.label == "价格上限（USD）"
    )
    symbol = next(e for e in page.elements.values() if isinstance(e, ui.select) and e.label == "币种")
    lower.set_value(75000)
    upper.set_value(91000)
    symbol.set_value("ETH")
    assert lower.value is None and upper.value is None
    dialog.delete()


async def test_late_btc_range_response_cannot_overwrite_eth_parameters(page, env, monkeypatch):
    store, runtime, _, _ = env
    entered, release = asyncio.Event(), asyncio.Event()
    original_book = runtime.markets.book

    async def book(provider, symbol, *, refresh=False):
        entered.set()
        await release.wait()
        return await original_book(provider, symbol, refresh=refresh)

    monkeypatch.setattr(runtime.markets, "book", book)

    async def saved():
        pass

    with page:
        dialog = grid_dialog(store, runtime, "late-quote-grid", saved)
    tasks = click(page, "填入当前价 ±10%")
    await asyncio.wait_for(entered.wait(), timeout=1)
    symbol = next(e for e in page.elements.values() if isinstance(e, ui.select) and e.label == "币种")
    symbol.set_value("ETH")
    release.set()
    await asyncio.gather(*tasks)
    for e in page.elements.values():
        if isinstance(e, ui.number) and e.label in {"价格下限（USD）", "价格上限（USD）"}:
            assert e.value is None
    dialog.delete()


async def test_form_save_performs_native_minimum_check_and_preserves_draft(page, env):
    store, runtime, account, _ = env

    async def saved():
        pass

    with page:
        grid_dialog(store, runtime, "invalid-ui-save", saved)
    for e in page.elements.values():
        if isinstance(e, ui.number):
            if e.label == "价格下限（USD）":
                e.set_value(58000)
            elif e.label == "价格上限（USD）":
                e.set_value(62000)
            elif e.label == "名义仓位预算（USD）":
                e.set_value(10)
    await asyncio.gather(*click(page, "保存 Bot"))
    assert store.bots() == [] and runtime.accounts.adapter(account.id).sent == []
    assert any(isinstance(e, ui.label) and "预算至少" in e.text for e in page.elements.values())
    budget = next(
        e for e in page.elements.values() if isinstance(e, ui.number) and e.label == "名义仓位预算（USD）"
    )
    assert budget.value == 10 and budget.enabled
