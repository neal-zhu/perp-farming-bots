"""Native units, pre-trade configuration confirmation and explicit legacy migration."""

import asyncio
import json
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import FixtureMarkets, connection_value
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import update
from test_grid import grid_bot, grid_market

from perp_farming_bots.api import register_routes
from perp_farming_bots.markets import VenueRequestError
from perp_farming_bots.models import (
    BotCreate,
    BotState,
    BotUpdate,
    ConnectionCreate,
    GridMarginCapital,
    GridParameters,
    Provider,
)
from perp_farming_bots.notifications import Notifications
from perp_farming_bots.store import Store, bots, fills, operations
from perp_farming_bots.trading import Arcus, Lighter


def capital(amount="248", leverage=10, mode="isolated"):
    return GridMarginCapital(kind="margin", investment_usd=amount, leverage=leverage, margin_mode=mode)


def lighter_value(provider=Provider.LIGHTER_RH):
    return ConnectionCreate(
        name="test account",
        provider=provider,
        account_index=123,
        api_key_index=2,
        api_private_key=SecretStr("33" * 32),
    )


@pytest.mark.parametrize("provider", [Provider.LIGHTER, Provider.LIGHTER_RH])
@pytest.mark.parametrize("imf,expected", [("50.00", Decimal(2)), ("5.00", Decimal(20))])
async def test_native_lighter_account_percent_is_distinct_from_rule_integer_units(provider, imf, expected):
    markets = FixtureMarkets()
    markets.request = AsyncMock(
        side_effect=[
            {"order_book_details": [{"market_id": 1, "symbol": "BTC", "min_initial_margin_fraction": 200}]},
            {
                "accounts": [
                    {
                        "account_index": 123,
                        "positions": [
                            {
                                "market_id": 1,
                                "symbol": "BTC",
                                "initial_margin_fraction": imf,
                                "margin_mode": 1,
                                "allocated_margin": "3.25",
                            }
                        ],
                    }
                ]
            },
        ]
    )
    try:
        snapshot = await Lighter(lighter_value(provider), markets).margin("BTC")
        assert snapshot.leverage == expected and snapshot.max_leverage == 50
        assert snapshot.margin_mode == "isolated" and snapshot.position_margin == Decimal("3.25")
    finally:
        await markets.close()


@pytest.mark.parametrize("imf", [None, "0", "NaN"])
async def test_native_lighter_missing_or_invalid_settings_are_not_defaulted(imf):
    markets = FixtureMarkets()
    markets.request = AsyncMock(
        side_effect=[
            {"order_book_details": [{"market_id": 1, "symbol": "BTC", "min_initial_margin_fraction": 200}]},
            {
                "accounts": [
                    {
                        "account_index": 123,
                        "positions": []
                        if imf is None
                        else [
                            {
                                "market_id": 1,
                                "symbol": "BTC",
                                "initial_margin_fraction": imf,
                                "margin_mode": 0,
                            }
                        ],
                    }
                ]
            },
        ]
    )
    try:
        if imf is None:
            snapshot = await Lighter(lighter_value(), markets).margin("BTC")
            assert snapshot.leverage is None and snapshot.margin_mode is None
        else:
            with pytest.raises(ValueError):
                await Lighter(lighter_value(), markets).margin("BTC")
    finally:
        await markets.close()


@pytest.mark.parametrize("invalid", [None, "identity", "mode"])
async def test_arcus_reads_effective_settings_and_checks_identity_and_mode(invalid):
    value = connection_value()
    markets = FixtureMarkets()
    markets.request = AsyncMock(
        side_effect=[
            {"markets": [{"marketId": 1, "baseAsset": "BTC", "initialMarginFraction": "0.025"}]},
            {
                "address": "0x" + "00" * 20 if invalid == "identity" else value.address,
                "accountIndex": 0,
                "leverages": [
                    {
                        "marketId": 1,
                        "marketDisplayName": "BTC",
                        "leverage": 5,
                        "isolated": True,
                        "marginMode": "CROSS" if invalid == "mode" else "ISOLATED",
                    }
                ],
            },
            {
                "address": value.address,
                "accountIndex": 0,
                "positions": {"1": {"marketDisplayName": "BTC", "size": "0.002", "marginUsed": "24.0"}},
            },
        ]
    )
    try:
        if invalid:
            with pytest.raises(ValueError):
                await Arcus(value, markets).margin("BTC")
        else:
            snapshot = await Arcus(value, markets).margin("BTC")
            assert snapshot.leverage == 5 and snapshot.max_leverage == 40
            assert snapshot.margin_mode == "isolated" and snapshot.position_margin == 24
    finally:
        await markets.close()


async def test_arcus_margin_signature_uses_documented_legacy_message_without_sending():
    markets = FixtureMarkets()
    markets.request = AsyncMock()
    adapter = Arcus(connection_value(), markets)
    try:
        prepared = await adapter.prepare_margin("BTC", capital(leverage=5))
        headers, body = prepared["headers"], prepared["body"]
        assert body["leverage"] == 5 and body["isolated"] is True
        assert abs(time.time_ns() - int(headers["X-Timestamp"])) < 1_000_000_000
        adapter.key.public_key().verify(
            bytes.fromhex(headers["X-Signature"]),
            (
                headers["X-Timestamp"]
                + "setLeverage"
                + json.dumps(body, sort_keys=True, separators=(",", ":"))
            ).encode(),
        )
        assert markets.request.await_count == 0
        markets.request.return_value = {"status": "ACK", "requestId": "native-ack"}
        assert await adapter.send_margin(prepared) == "native-ack"
        call = markets.request.call_args
        assert call.args == (Provider.ARCUS, "POST", "/v1/setLeverage")
        assert call.kwargs["json"] == body and call.kwargs["headers"] == headers
    finally:
        await markets.close()


@pytest.mark.parametrize("provider,chain_id", [(Provider.LIGHTER, 304), (Provider.LIGHTER_RH, 466324)])
async def test_lighter_signs_margin_without_send_using_exact_units_and_profile(
    monkeypatch, provider, chain_id
):
    calls = []

    class Signer:
        CROSS_MARGIN_MODE = 0
        ISOLATED_MARGIN_MODE = 1

        def __init__(self, **kwargs):
            calls.append(kwargs)

        def sign_update_leverage(self, **kwargs):
            calls.append(kwargs)
            return 20, "signed-setting", "setting-hash", None

        async def close(self):
            pass

    monkeypatch.setattr("perp_farming_bots.trading.lighter.SignerClient", Signer)
    markets = FixtureMarkets()
    markets.request = AsyncMock(return_value={"nonce": 42})
    try:
        prepared = await Lighter(lighter_value(provider), markets).prepare_margin("BTC", capital(leverage=5))
        assert calls[0]["chain_id"] == chain_id
        assert calls[1] == {
            "market_index": 1,
            "fraction": 2000,
            "margin_mode": 1,
            "nonce": 42,
            "api_key_index": 2,
        }
        assert prepared["tx_hash"] == "setting-hash"
        assert markets.request.await_count == 1 and markets.request.call_args.args[1] == "GET"
    finally:
        await markets.close()


async def test_margin_grid_save_checks_collateral_not_notional_and_never_changes_native_settings(
    env, monkeypatch
):
    store, runtime, account, _ = env
    adapter = runtime.accounts.adapter(account.id)
    original = adapter.snapshot

    async def snapshot():
        return (await original()).model_copy(update={"available": Decimal(300)})

    monkeypatch.setattr(adapter, "snapshot", snapshot)
    value = BotCreate(
        name="margin grid",
        request_id="margin-save",
        strategy="grid",
        parameters=GridParameters(
            connection_id=account.id,
            symbol="BTC",
            direction="neutral",
            lower_price=58000,
            upper_price=62000,
            grid_count=4,
            capital=capital(),
        ),
    )
    preview = await runtime.preview(value)
    assert preview.notional_limit == 2480 and preview.collateral_budget == 248
    assert preview.minimum_collateral == Decimal("12.4") and preview.quantity_per_grid == Decimal("0.02")
    app = FastAPI()
    register_routes(app, store, runtime, Notifications(store, runtime.accounts.secrets))
    with TestClient(app) as client:
        response = client.post("/api/bots", json=value.model_dump(mode="json"))
    assert response.status_code == 201
    assert adapter.margin_sent == [] and adapter.sent == [] and adapter.margin_leverage == 2
    assert store.bot_margin_changes(response.json()["id"]) == []


async def test_settings_are_encrypted_and_journaled_before_single_send_lost_ack_can_be_confirmed(
    env, monkeypatch
):
    store, runtime, account, _ = env
    bot = grid_bot(store, account, capital=capital())
    adapter = runtime.accounts.adapter(account.id)
    original = adapter.send_margin

    async def lost_ack(prepared):
        change = store.bot_margin_changes(bot.id, public=False)[0]
        assert change["status"] == "pending" and store.bot_pending(bot.id)
        assert json.loads(runtime.accounts.secrets.decrypt(change["payload"])) == prepared
        assert "payload" not in store.bot_margin_changes(bot.id)[0]
        await original(prepared)
        raise TimeoutError("test lost acknowledgement")

    monkeypatch.setattr(adapter, "send_margin", lost_ack)
    await runtime.command(bot.id, "run")
    assert len(adapter.margin_sent) == 1 and adapter.sent == []
    assert store.bot(bot.id).state == BotState.WAITING
    assert store.bot_margin_changes(bot.id)[0]["status"] == "confirmed"
    assert not store.bot_pending(bot.id)


async def test_unconfirmed_settings_timeout_blocks_execution_then_readonly_sync_requires_resume(
    env, monkeypatch
):
    store, runtime, account, _ = env
    bot = grid_bot(store, account, capital=capital())
    adapter = runtime.accounts.adapter(account.id)
    adapter.send_margin = AsyncMock(return_value="ack-only")
    monkeypatch.setattr("perp_farming_bots.margin.CONFIRM_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(ValueError, match="尚未确认"):
        await runtime.command(bot.id, "run")
    assert store.bot(bot.id).state == BotState.ATTENTION and store.bot_pending(bot.id)
    assert not await runtime.grid.tick(bot.id) and adapter.sent == []
    await runtime.sync(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION
    adapter.margin_leverage, adapter.margin_mode = Decimal(10), "isolated"
    await runtime.sync(bot.id)
    assert store.bot(bot.id).state == BotState.PAUSED and not store.bot_pending(bot.id)
    assert adapter.send_margin.await_count == 1 and adapter.sent == []
    await runtime.command(bot.id, "run")
    assert store.bot(bot.id).state == BotState.WAITING
    assert adapter.send_margin.await_count == 1


async def test_confirmation_read_itself_has_total_timeout_and_preserves_unknown(env, monkeypatch):
    store, runtime, account, _ = env
    bot = grid_bot(store, account, capital=capital())
    adapter = runtime.accounts.adapter(account.id)
    original = adapter.margin
    adapter.send_margin = AsyncMock(return_value="ack")

    async def blocked_read(symbol):
        if adapter.send_margin.await_count:
            await asyncio.Event().wait()
        return await original(symbol)

    monkeypatch.setattr(adapter, "margin", blocked_read)
    monkeypatch.setattr("perp_farming_bots.margin.CONFIRM_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(ValueError, match="尚未确认"):
        await asyncio.wait_for(runtime.command(bot.id, "run"), timeout=1)
    assert store.bot_margin_changes(bot.id)[0]["status"] == "unknown"
    assert adapter.sent == [] and adapter.send_margin.await_count == 1


async def test_definite_native_rejection_is_recorded_and_never_enables_grid(env):
    store, runtime, account, _ = env
    bot = grid_bot(store, account, capital=capital())
    adapter = runtime.accounts.adapter(account.id)
    adapter.send_margin = AsyncMock(side_effect=VenueRequestError("native setting rejected", 422))
    with pytest.raises(ValueError, match="rejected"):
        await runtime.command(bot.id, "run")
    assert store.bot(bot.id).state == BotState.ATTENTION
    assert store.bot_margin_changes(bot.id)[0]["status"] == "rejected"
    assert not store.bot_pending(bot.id) and adapter.sent == []
    assert adapter.send_margin.await_count == 1


async def test_native_setting_change_blocks_new_grid_actions_but_manual_reduce_close_works(env, monkeypatch):
    store, runtime, account, _ = env
    prices, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long", capital=capital())
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id) and adapter.net > 0
    original_inventory = adapter.net
    adapter.margin_leverage = Decimal(2)
    prices.update(bid=Decimal("58999"), ask=Decimal("58999.5"))
    assert not await runtime.grid.tick(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION and adapter.net == original_inventory
    assert len(adapter.sent) == 1
    await runtime.command(bot.id, "close")
    assert adapter.sent[-1].reduce_only and adapter.net == 0
    assert store.bot(bot.id).state == BotState.CLOSED and len(adapter.margin_sent) == 1


@pytest.mark.parametrize(
    "leverage,provider,error", [(100, Provider.ARCUS, "最高"), (3, Provider.LIGHTER_RH, "精确")]
)
async def test_native_limits_and_unrepresentable_leverage_reject_before_save_or_submission(
    env, leverage, provider, error
):
    store, runtime, account, _ = env
    with store.transaction() as db:
        from perp_farming_bots.store import connections

        db.execute(update(connections).where(connections.c.id == account.id).values(provider=provider.value))
    bot = grid_bot(store, account, capital=capital(leverage=leverage))
    with pytest.raises(ValueError, match=error):
        await runtime.preview(bot)
    assert runtime.accounts.adapter(account.id).margin_sent == []


async def test_schema_five_migration_keeps_legacy_notional_and_all_execution_evidence(env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    before = (
        store.grid_state(bot.id),
        store.positions(bot.id),
        store.bot_orders(bot.id),
        store.rows(fills, bot.id),
        store.rows(operations, bot.id),
        store.turnover(bot.id),
    )
    legacy = bot.parameters.model_dump(mode="json", exclude={"capital"})
    legacy["budget_usd"] = "2480"
    with store.transaction() as db:
        db.execute(update(bots).where(bots.c.id == bot.id).values(parameters=json.dumps(legacy)))
        db.exec_driver_sql("PRAGMA user_version=5")
        db.exec_driver_sql("DROP TABLE margin_changes")
    migrated = Store(Path(store.engine.url.database))
    try:
        p = migrated.bot(bot.id).parameters
        assert p.capital.kind == "notional" and p.notional_limit == 2480
        assert (
            migrated.grid_state(bot.id),
            migrated.positions(bot.id),
            migrated.bot_orders(bot.id),
            migrated.rows(fills, bot.id),
            migrated.rows(operations, bot.id),
            migrated.turnover(bot.id),
        ) == before
        assert migrated.bot_margin_changes(bot.id) == [] and adapter.margin_sent == []
    finally:
        migrated.close()


async def test_only_closed_flat_grid_can_convert_legacy_capital_preserving_history(env, monkeypatch):
    store, runtime, account, _ = env
    await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    changed = BotUpdate(
        name=bot.name,
        parameters=bot.parameters.model_copy(update={"capital": capital(), "slippage_bps": Decimal(30)}),
    )
    with pytest.raises(ValueError):
        store.update_bot(bot.id, changed)
    await runtime.command(bot.id, "close")
    before = store.bot_orders(bot.id), store.rows(fills, bot.id), store.turnover(bot.id)
    await runtime.validate_configuration(changed, bot_id=bot.id)
    edited = store.update_bot(bot.id, changed)
    assert edited.state == BotState.CLOSED and store.grid_state(bot.id) is None
    assert (store.bot_orders(bot.id), store.rows(fills, bot.id), store.turnover(bot.id)) == before
    assert len(runtime.accounts.adapter(account.id).margin_sent) == 0


async def test_old_budget_api_payload_is_explicitly_invalid_instead_of_silently_mapped(env):
    store, _, account, _ = env
    p = grid_bot(store, account).parameters.model_dump(mode="json", exclude={"capital"})
    p["budget_usd"] = "20"
    with pytest.raises(ValidationError):
        GridParameters.model_validate(p)


async def test_migration_rejects_ambiguous_dual_capital_instead_of_overwriting_it(env):
    store, _, account, _ = env
    bot = grid_bot(store, account)
    ambiguous = bot.parameters.model_dump(mode="json")
    ambiguous["budget_usd"] = "20"
    with store.transaction() as db:
        db.execute(update(bots).where(bots.c.id == bot.id).values(parameters=json.dumps(ambiguous)))
        db.exec_driver_sql("PRAGMA user_version=5")
    with pytest.raises(ValueError, match="同时存在"):
        Store(Path(store.engine.url.database))
    with store.engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA user_version").scalar_one() == 5
