"""Isolated native Ondo protocol evidence. Never sends a funded request."""

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from nicegui import ui
from pydantic import SecretStr, ValidationError
from test_account_form import click
from test_account_form import page as page
from test_runtime import make_bot

from perp_farming_bots.grid_ui import grid_dialog
from perp_farming_bots.markets import Markets, require_fresh_book
from perp_farming_bots.models import BotCreate, ConnectionCreate, GridMarginCapital, OrderIntent, Provider
from perp_farming_bots.ondo import Ondo, OndoRequestError
from perp_farming_bots.trading import Accounts, OrderRejected

KEY_ID = "ondoKeyId_test_only"
SECRET = "ondoApiSecret_" + "x" * 40
MARKET = "BTC-USD.P"


def utc(stamp=None):
    return datetime.fromtimestamp(time.time() if stamp is None else stamp, timezone.utc).isoformat()


def credentials(**changes):
    return ConnectionCreate(
        name="Ondo 1",
        provider=Provider.ONDO,
        api_key_id=SecretStr(KEY_ID),
        api_private_key=SecretStr(SECRET),
        **changes,
    )


def intent():
    return OrderIntent(
        connection_id="ondo",
        symbol=MARKET,
        side="buy",
        quantity="0.002",
        limit_price="60000",
        reduce_only=False,
        client_id="aa" * 16,
    )


@pytest.fixture
async def ondo():
    markets = Markets()
    await markets.http.aclose()
    adapter = Ondo(credentials(), markets)
    pair = {
        "market": MARKET,
        "baseIncrement": "0.0001",
        "quoteIncrement": "1",
        "marginInfo": [{"maxLeverage": "40", "positionBracketUsd": "1000000"}],
    }
    order = {
        "orderId": "native_1",
        "clientOrderId": intent().client_id,
        "market": MARKET,
        "side": "buy",
        "type": "limit",
        "timeInForce": "IOC",
        "reduceOnly": False,
        "price": "60000",
        "size": "0.002",
        "filledSize": "0.002",
        "filledCost": "119.998",
        "fee": "0.03",
        "status": "fullyfilled",
    }
    fill = {
        "id": "fill_1",
        "orderId": "native_1",
        "clientOrderId": intent().client_id,
        "market": MARKET,
        "side": "buy",
        "size": "0.002",
        "price": "59999",
        "filledCost": "119.998",
        "fee": "0.03",
        "feeRebate": "0.001",
        "time": utc(),
    }
    data = {
        "/v1/account": {
            "accountID": "10458932786832481",
            "accountState": "open",
            "disabledFunctionality": {"disablePerps": False},
        },
        "/v1/api_keys": [{"keyId": KEY_ID, "scopes": ["trade"]}],
        "/v1/markets": {"perps": {"tradingPairs": [pair]}, "spot": {"tradingPairs": []}},
        "/v1/perps/contracts": [
            {
                "market": MARKET,
                "productType": "perpetual",
                "contractType": "linear",
                "quoteCurrency": "USD",
                "disabled": False,
            }
        ],
        "/v1/perps/positions": [],
        "/v1/perps/balance": {
            "marginBalance": "1000.125",
            "availableMargin": "950.25",
            "underLiquidation": False,
        },
        "/v1/perps/leverage": [{"market": MARKET, "leverage": "3"}],
        "/v1/perps/depth": {
            "market": MARKET,
            "time": utc(),
            "bids": [["59999", "10"]],
            "asks": [["60000", "10"]],
        },
        "/v1/perps/funding_rates": {
            "market": MARKET,
            "rate": "0.0000125",
            "intervalEnds": utc(time.time() + 1800),
        },
        "/v1/perps/funding_rate_history": [
            {"market": MARKET, "fundingRate": "0.0000120", "time": utc(time.time() - 1800)}
        ],
        "/v1/perps/orders": [],
        "/v1/perps/twap/orders/running": [],
        "/v1/perps/orders/client:" + intent().client_id: order,
        "/v1/perps/orders/native_1/fills": [fill],
    }
    calls = []

    def handle(request):
        calls.append(request)
        if "ONDO-SIGN" in request.headers:
            exact = (
                request.headers["ONDO-TIMESTAMP"]
                + request.method
                + request.url.raw_path.decode()
                + request.content.decode()
            )
            assert (
                request.headers["ONDO-SIGN"]
                == hmac.new(SECRET.encode(), exact.encode(), hashlib.sha256).hexdigest()
            )
            assert request.headers["ONDO-KEY-ID"] == KEY_ID
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "result": order})
        return httpx.Response(200, json={"success": True, "result": data[request.url.path]})

    markets.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    yield markets, adapter, data, calls
    await markets.close()


async def test_connect_uses_hmac_reads_binds_native_account_and_requires_trade_permission(ondo):
    _, adapter, data, calls = ondo
    snapshot = await adapter.validate()
    assert adapter.value.account_id == "10458932786832481"
    assert snapshot.available == Decimal("950.25") and snapshot.equity == Decimal("1000.125")
    assert all(r.method == "GET" for r in calls)
    data["/v1/api_keys"][0]["scopes"] = []
    with pytest.raises(ValueError, match="交易权限"):
        await adapter.validate()
    data["/v1/account"]["accountID"] = "foreign_account"
    with pytest.raises(ValueError, match="不匹配"):
        await adapter.snapshot()


async def test_storage_encrypts_key_id_and_preserves_account_identity_on_restart(ondo, env, monkeypatch):
    markets, _, _, _ = ondo
    store, runtime, _, _ = env
    runtime.accounts.markets = markets
    monkeypatch.setattr(runtime.accounts, "adapter_for", Accounts.adapter_for.__get__(runtime.accounts))
    connection = await runtime.accounts.add(credentials())
    assert connection.account_ref == "10458932786832481"
    assert KEY_ID not in connection.model_dump_json()
    assert SECRET not in store.credentials(connection.id) and KEY_ID not in store.credentials(connection.id)
    runtime.accounts.adapters.clear()
    assert (await runtime.accounts.refresh(connection.id)).available == Decimal("950.25")
    with pytest.raises(ValueError, match="已经添加"):
        await runtime.accounts.add(credentials())


async def test_catalog_native_tickers_precision_disabled_markets_unknown_floor_and_hourly_funding(ondo):
    markets, _, data, _ = ondo
    assert await markets.catalog(Provider.ONDO) == [MARKET]
    spec = await markets.spec(Provider.ONDO, MARKET)
    assert spec.market_id == MARKET and spec.quantity_step == Decimal("0.0001")
    assert spec.min_notional is None and not spec.minimums_known()
    assert spec.min_quantity == spec.quantity_step and spec.max_leverage == 40
    assert (await markets.book(Provider.ONDO, MARKET)).fresh()
    funding = await markets.funding(Provider.ONDO, MARKET)
    assert funding.status == "available" and funding.interval_seconds == 3600
    assert funding.predicted_rate_pct == Decimal("0.00125")
    data["/v1/perps/contracts"][0]["disabled"] = True
    assert await markets.catalog(Provider.ONDO, refresh=True) == []


async def test_preparation_never_writes_and_exact_ioc_body_is_signed_and_sent_once(ondo):
    _, adapter, _, calls = ondo
    await adapter.validate()
    prepared = await adapter.prepare(intent())
    assert all(r.method == "GET" for r in calls)
    body = json.loads(prepared["body"])
    assert body["size"] == "0.002" and body["price"] == "60000"
    assert body["timeInForce"] == "IOC" and body["reduceOnly"] is False
    assert "builderCode" not in body
    assert await adapter.send(prepared) == "native_1"
    writes = [r for r in calls if r.method == "POST"]
    assert len(writes) == 1 and writes[0].content.decode() == prepared["body"]


async def test_original_lookup_and_complete_fills_confirm_money_with_native_rebate(ondo):
    _, adapter, _, calls = ondo
    await adapter.validate()
    result = await adapter.lookup(intent(), None)
    assert result.status == "filled" and result.quantity == Decimal("0.002")
    assert result.average_price == 59999 and result.fee == Decimal("0.029")
    assert any(b"client%3A" in r.url.raw_path for r in calls)
    assert not any(r.method != "GET" for r in calls)


async def test_partial_canceled_ioc_missing_rebate_and_incomplete_fills_are_explicit(ondo):
    _, adapter, data, _ = ondo
    await adapter.validate()
    order = data["/v1/perps/orders/client:" + intent().client_id]
    fill = data["/v1/perps/orders/native_1/fills"][0]
    order.update(status="canceled", filledSize="0.001", filledCost="59.999", fee="0.015")
    fill.update(size="0.001", filledCost="59.999", fee="0.015", feeRebate="0")
    result = await adapter.lookup(intent(), "native_1")
    assert (
        result.status == "canceled" and result.quantity == Decimal("0.001") and result.fee == Decimal("0.015")
    )
    del fill["feeRebate"]
    assert (await adapter.lookup(intent(), "native_1")).fee is None
    data["/v1/perps/orders/native_1/fills"] = []
    assert (await adapter.lookup(intent(), "native_1")).status == "unknown"


@pytest.mark.parametrize(
    "field,value",
    [
        ("clientOrderId", "foreign"),
        ("market", "ETH-USD.P"),
        ("side", "sell"),
        ("size", "0.003"),
        ("price", "60001"),
        ("timeInForce", "GTC"),
        ("reduceOnly", True),
        ("orderId", "foreign"),
    ],
)
async def test_wrong_original_identity_never_applies_inventory(ondo, field, value):
    _, adapter, data, _ = ondo
    await adapter.validate()
    data["/v1/perps/orders/client:" + intent().client_id][field] = value
    with pytest.raises(ValueError, match="身份"):
        await adapter.lookup(intent(), "native_1")


async def test_duplicate_fills_and_stale_book_are_rejected(ondo):
    markets, adapter, data, _ = ondo
    await adapter.validate()
    fills = data["/v1/perps/orders/native_1/fills"]
    fills.append(fills[0].copy())
    with pytest.raises(ValueError, match="重复"):
        await adapter.lookup(intent(), None)
    data["/v1/perps/depth"]["time"] = utc(time.time() - 100)
    with pytest.raises(ValueError, match="秒时效"):
        require_fresh_book(await markets.book(Provider.ONDO, MARKET, refresh=True))


async def test_cross_leverage_uses_native_settings_and_journal_ready_signed_request(ondo):
    _, adapter, _, calls = ondo
    await adapter.validate()
    assert (await adapter.margin(MARKET)).leverage == 3
    assert (await adapter.margin(MARKET)).margin_mode == "cross"
    with pytest.raises(ValueError, match="全仓"):
        await adapter.prepare_margin(
            MARKET, GridMarginCapital(investment_usd=100, leverage=3, margin_mode="isolated")
        )
    prepared = await adapter.prepare_margin(
        MARKET, GridMarginCapital(investment_usd=100, leverage=4, margin_mode="cross")
    )
    assert all(r.method == "GET" for r in calls)
    assert json.loads(prepared["body"]) == {"market": MARKET, "leverage": "4"}
    await adapter.send_margin(prepared)
    assert len([r for r in calls if r.method == "POST"]) == 1


@pytest.mark.parametrize(
    "status,code,error",
    [
        (400, "order_invalid_size", OrderRejected),
        (400, "clientOrderID_collision", OndoRequestError),
        (400, "must_use_delayed_path", OndoRequestError),
        (400, "redirect", OndoRequestError),
        (503, "service_unavailable", OndoRequestError),
    ],
)
async def test_only_explicit_validation_rejections_are_terminal_and_write_never_retries(
    ondo, status, code, error
):
    markets, adapter, _, _ = ondo
    await adapter.validate()
    prepared = await adapter.prepare(intent())
    attempts = []

    def handle(request):
        attempts.append(request)
        return httpx.Response(status, json={"success": False, "error_code": code, "error": SECRET})

    await markets.http.aclose()
    markets.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with pytest.raises(error) as caught:
        await adapter.send(prepared)
    assert SECRET not in str(caught.value) and KEY_ID not in str(caught.value)
    assert len(attempts) == 1


async def test_not_found_is_unknown_and_expired_prepared_request_is_never_sent(ondo, monkeypatch):
    _, adapter, _, _ = ondo
    await adapter.validate()
    read = adapter.get

    async def absent(path, **params):
        if "/orders/client" in path:
            raise OndoRequestError(400, "order_not_found")
        return await read(path, **params)

    monkeypatch.setattr(adapter, "get", absent)
    assert (await adapter.lookup(intent(), None)).status == "unknown"
    prepared = await adapter.prepare(intent())
    prepared["headers"]["ONDO-TIMESTAMP"] = str(int((time.time() - 11) * 1000))
    request = AsyncMock()
    monkeypatch.setattr(adapter.markets, "request_response", request)
    with pytest.raises(ValueError, match="过期"):
        await adapter.send(prepared)
    request.assert_not_awaited()


async def test_confirmed_native_rejection_is_journaled_and_prevents_peer_leg(env, monkeypatch):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    sender = runtime.accounts.adapter(a.id)
    monkeypatch.setattr(sender, "send", AsyncMock(side_effect=OrderRejected("native validated rejection")))
    await runtime.command(bot.id, "run")
    await runtime.try_open(bot.id)
    orders = store.bot_orders(bot.id)
    assert len(orders) == 1 and orders[0]["status"] == "rejected"
    assert not runtime.accounts.adapter(b.id).sent and not store.positions(bot.id)


async def test_ondo_form_shows_only_key_id_secret_and_submits_no_wallet(page, env, monkeypatch):
    _, runtime, a, _ = env
    add = AsyncMock(return_value=a)
    monkeypatch.setattr(runtime.accounts, "add", add)
    click(page, "连接账户")
    provider = next(e for e in page.elements.values() if isinstance(e, ui.select) and e.label == "交易所")
    provider.set_value(Provider.ONDO.value)
    for element in page.elements.values():
        if isinstance(element, ui.input):
            if element.label.startswith("账户昵称"):
                element.set_value("Ondo test")
            elif element.label == "API Key ID":
                element.set_value(KEY_ID)
            elif element.label == "API Secret":
                element.set_value(SECRET)
    await asyncio.gather(*click(page, "验证并连接账户"))
    value = add.call_args.args[0]
    assert value.provider == Provider.ONDO and value.api_key_id.get_secret_value() == KEY_ID
    assert value.address is value.account_index is value.api_key_index is None


def test_ondo_credentials_reject_aliases_and_missing_native_prefixes():
    with pytest.raises(ValidationError):
        credentials(address="0x" + "11" * 20)
    with pytest.raises(ValidationError):
        ConnectionCreate(name="bad", provider=Provider.ONDO, api_private_key=SecretStr(SECRET))


async def test_grid_preview_does_not_invent_verified_minimum_budget_when_floor_unknown(env, monkeypatch):
    _, runtime, a, _ = env
    original = runtime.markets.spec

    async def unpublished(provider, symbol):
        return (await original(provider, symbol)).model_copy(update={"min_notional": None})

    monkeypatch.setattr(runtime.markets, "spec", unpublished)
    value = BotCreate(
        name="grid",
        strategy="grid",
        request_id="unknown-floor-test",
        parameters={
            "connection_id": a.id,
            "symbol": "BTC",
            "direction": "neutral",
            "lower_price": "50000",
            "upper_price": "70000",
            "grid_count": 10,
            "open_position_on_start": False,
            "capital": {"investment_usd": "1000", "leverage": 2, "margin_mode": "cross"},
        },
    )
    preview = await runtime.grid.preview(value)
    assert preview.minimum_collateral is preview.minimum_quantity_per_grid is None
    assert preview.quantity_per_grid > 0


def test_ondo_grid_form_restricts_mode_to_cross_before_save(page, env):
    store, runtime, a, _ = env
    connection = store.add_connection(
        credentials(account_id="native_ondo"), runtime.accounts.snapshots[a.id], "test-only"
    )
    with page:
        grid_dialog(store, runtime, "ondo-cross-grid", lambda: None)
    account = next(e for e in page.elements.values() if isinstance(e, ui.select) and e.label == "交易账户")
    mode = next(e for e in page.elements.values() if isinstance(e, ui.select) and e.label == "保证金模式")
    account.set_value(connection.id)
    assert mode.value == "cross" and set(mode.options) == {"cross"}


async def test_open_regular_orders_and_running_twaps_block_exclusive_grid(ondo):
    _, adapter, data, _ = ondo
    await adapter.validate()
    data["/v1/perps/orders"] = [{"market": MARKET, "orderId": "resting_order"}]
    data["/v1/perps/twap/orders/running"] = [{"market": MARKET, "orderId": "twap_order"}]
    assert len(await adapter.open_orders(MARKET)) == 2


@pytest.mark.parametrize("value", [None, "-0.001", True])
async def test_invalid_rebate_never_becomes_zero(ondo, value):
    _, adapter, data, _ = ondo
    await adapter.validate()
    data["/v1/perps/orders/native_1/fills"][0]["feeRebate"] = value
    with pytest.raises(ValueError):
        await adapter.lookup(intent(), None)
