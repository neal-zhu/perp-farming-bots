"""Offline native Hyperliquid protocol tests, with test-only signing keys."""

import json
import time
from decimal import Decimal

import httpx
import pytest
from eth_account import Account
from pydantic import SecretStr, ValidationError
from test_account_form import page as page

from perp_farming_bots.entropy import ENTROPY_BUILDER, Entropy
from perp_farming_bots.markets import Markets, VenueRequestError
from perp_farming_bots.models import ConnectionCreate, GridMarginCapital, OrderIntent, Provider
from perp_farming_bots.runtime import bounded_price


@pytest.fixture
async def entropy():
    markets = Markets()
    await markets.http.aclose()
    value = ConnectionCreate(
        name="Entropy 1",
        provider=Provider.ENTROPY,
        address="0x" + "11" * 20,
        api_private_key=SecretStr("22" * 32),
    )
    adapter = Entropy(value, markets)
    calls = []
    native = {
        "coin": "BTC",
        "side": "B",
        "limitPx": "60000",
        "sz": "0",
        "oid": 42,
        "timestamp": int(time.time() * 1000) - 1000,
        "origSz": "0.001",
        "reduceOnly": False,
        "cloid": "0x" + "aa" * 16,
    }
    fill = {
        "coin": "BTC",
        "side": "B",
        "sz": "0.001",
        "px": "59999",
        "oid": 42,
        "tid": 7,
        "fee": "0.02699955",
        "feeToken": "USDC",
        "builderFee": "0",
    }
    data = {
        "perpDexs": [None, {"name": "xyz"}, {"name": "io"}],
        "meta": {
            "collateralToken": 0,
            "universe": [
                {"name": "BTC", "szDecimals": 5, "maxLeverage": 40},
                {"name": "ETH", "szDecimals": 4, "maxLeverage": 25},
                {"name": "HYPE", "szDecimals": 2, "maxLeverage": 3},
            ]
        },
        "meta_io": {
            "collateralToken": 0,
            "universe": [
                {"name": "io:BTC", "szDecimals": 5, "maxLeverage": 3},
                {"name": "io:OAI", "szDecimals": 3, "maxLeverage": 6, "onlyIsolated": True},
            ],
        },
        "userAbstraction": "dexAbstraction",
        "clearinghouseState": {
            "time": int(time.time() * 1000),
            "assetPositions": [],
            "marginSummary": {"accountValue": "1000.50"},
            "withdrawable": "950.40",
        },
        "clearinghouseState_io": {
            "time": int(time.time() * 1000), "assetPositions": [],
            "marginSummary": {"accountValue": "0"}, "withdrawable": "0",
        },
        "extraAgents": [{"address": adapter.key.address, "validUntil": int((time.time() + 86400) * 1000)}],
        "approvedBuilders": [ENTROPY_BUILDER],
        "activeAssetData": {
            "user": value.address,
            "coin": "BTC",
            "leverage": {"type": "isolated", "value": 3},
        },
        "openOrders": [{"coin": "ETH", "oid": 9}],
        "orderStatus": {"status": "order", "order": {"order": native, "status": "filled"}},
        "userFillsByTime": [fill],
        "l2Book": {
            "coin": "BTC",
            "time": int(time.time() * 1000),
            "levels": [[{"px": "59999", "sz": "1"}], [{"px": "60000", "sz": "1"}]],
        },
    }

    def handle(request):
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        if request.url.path == "/exchange":
            return httpx.Response(
                200, json={"status": "ok", "response": {"data": {"statuses": [{"filled": {"oid": 42}}]}}}
            )
        if payload["type"] == "userRole":
            role = (
                {"role": "user"}
                if payload["user"].lower() == value.address
                else {"role": "agent", "data": {"user": value.address}}
            )
            return httpx.Response(200, json=role)
        key = payload["type"] + ("_io" if payload.get("dex") == "io" and payload["type"] in {
            "meta", "clearinghouseState", "openOrders", "metaAndAssetCtxs"
        } else "")
        return httpx.Response(200, content=json.dumps(data[key]), headers={"Content-Type": "application/json"})

    markets.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    yield markets, adapter, data, calls
    await markets.close()


@pytest.fixture
def unified(entropy):
    _, _, data, _ = entropy
    data["userAbstraction"] = "unifiedAccount"
    data["spotClearinghouseState"] = {
        "balances": [
            {"coin": "USDC", "token": 0, "total": "1000.50", "hold": "50.10"},
            {"coin": "HYPE", "token": 150, "total": "500", "hold": "0"},
        ],
        "tokenToAvailableAfterMaintenance": [[150, "500"], [0, "900"]],
    }
    data["activeAssetData"]["availableToTrade"] = ["800", "700"]
    return entropy


def intent():
    return OrderIntent(
        connection_id="entropy",
        symbol="BTC",
        side="buy",
        quantity="0.001",
        limit_price="60000",
        reduce_only=False,
        client_id="aa" * 16,
    )


async def test_connect_only_reads_and_verifies_agent_owner_expiry_and_builder(entropy):
    _, adapter, data, calls = entropy
    snapshot = await adapter.validate()
    assert snapshot.equity == Decimal("1000.50") and snapshot.available == Decimal("950.40")
    assert all(path == "/info" for path, _ in calls)
    data["extraAgents"][0]["validUntil"] = 1
    with pytest.raises(ValueError, match="过期"):
        await adapter.validate()
    data["extraAgents"][0]["validUntil"] = int((time.time() + 86400) * 1000)
    data["approvedBuilders"] = []
    with pytest.raises(ValueError, match="交易授权"):
        await adapter.validate()


async def test_unified_account_connects_using_shared_spot_usdc_without_dex_double_counting(unified):
    _, adapter, data, calls = unified
    for key, coin in [("clearinghouseState", "BTC"), ("clearinghouseState_io", "io:OAI")]:
        data[key]["withdrawable"] = None  # Not meaningful under unified account.
        data[key]["marginSummary"]["accountValue"] = None
        data[key]["assetPositions"] = [{"position": {
            "coin": coin, "szi": "0.1", "entryPx": "1500", "unrealizedPnl": "2"
        }}]
    snapshot = await adapter.validate()
    assert snapshot.equity == Decimal("1000.50")
    assert snapshot.available == Decimal("900")
    assert {p.symbol for p in snapshot.positions} == {"BTC", "io:OAI"}
    assert "USDC" in snapshot.source
    assert all(path == "/info" for path, _ in calls)


@pytest.mark.parametrize("symbol", ["BTC", "io:OAI"])
async def test_unified_budget_uses_native_market_allowance_and_shared_collateral(unified, symbol):
    _, adapter, data, calls = unified
    data["activeAssetData"]["coin"] = symbol
    assert await adapter.available(symbol) == Decimal("700")
    assert calls[-1][1]["coin"] == symbol
    data["spotClearinghouseState"]["balances"][0]["hold"] = "600"
    assert await adapter.available(symbol) == Decimal("400.50")
    data["spotClearinghouseState"]["tokenToAvailableAfterMaintenance"][1][1] = "300"
    assert await adapter.available(symbol) == Decimal("300")
    data["activeAssetData"]["user"] = "0x" + "33" * 20
    with pytest.raises(ValueError, match="身份"):
        await adapter.available(symbol)
    assert all(path == "/info" for path, _ in calls)


@pytest.mark.parametrize("field,value", [
    ("balances", []),
    ("balances", [{"coin": "USDC", "token": 1, "total": "1000", "hold": "0"}]),
    ("balances", [{"coin": "FAKE", "token": 0, "total": "1000", "hold": "0"}]),
    ("balances", [{"coin": "USDC", "token": False, "total": "1000", "hold": "0"}]),
    ("balances", [{"coin": "USDC", "token": 0, "total": "NaN", "hold": "0"}]),
    ("balances", [{"coin": "USDC", "token": 0, "total": "1000", "hold": "-1"}]),
    ("balances", [{"coin": "USDC", "token": 0, "total": "1000", "hold": "0"}] * 2),
    ("tokenToAvailableAfterMaintenance", []),
    ("tokenToAvailableAfterMaintenance", [[0, "900"], [0, "900"]]),
    ("tokenToAvailableAfterMaintenance", [[0, None]]),
    ("tokenToAvailableAfterMaintenance", [[0, "Infinity"]]),
    ("tokenToAvailableAfterMaintenance", [[0, "invalid"]]),
    ("tokenToAvailableAfterMaintenance", None),
])
async def test_unified_unknown_collateral_never_uses_legacy_perp_balances(unified, field, value):
    _, adapter, data, _ = unified
    data["spotClearinghouseState"][field] = value
    with pytest.raises(ValueError, match="USDC 余额或可用额度未确认"):
        await adapter.validate()
    with pytest.raises(ValueError, match="USDC 余额或可用额度未确认"):
        await adapter.available("BTC")


async def test_unified_missing_limits_and_mode_changes_remain_explicit(unified):
    _, adapter, data, _ = unified
    del data["spotClearinghouseState"]["tokenToAvailableAfterMaintenance"]
    with pytest.raises(ValueError, match="未确认"):
        await adapter.snapshot()
    data["spotClearinghouseState"]["portfolioMarginEnabled"] = True
    with pytest.raises(ValueError, match="组合保证金"):
        await adapter.snapshot()


@pytest.mark.parametrize("limits", [None, [], ["100"], ["100", None], ["100", "NaN"]])
async def test_unified_missing_asset_limits_do_not_reuse_global_or_perp_balance(unified, limits):
    _, adapter, data, _ = unified
    data["activeAssetData"]["availableToTrade"] = limits
    with pytest.raises(ValueError, match="未确认|金额"):
        await adapter.available("BTC")


@pytest.mark.parametrize("mode,message", [
    ("portfolioMargin", "组合保证金"), ("futureMode", "无法识别账户模式"),
    (None, "无法识别账户模式"), ({"unexpected": True}, "无法识别账户模式"),
])
async def test_unsupported_account_modes_are_identified_without_mode_changes(entropy, mode, message):
    _, adapter, data, calls = entropy
    data["userAbstraction"] = mode
    with pytest.raises(ValueError, match=message):
        await adapter.validate()
    assert all(path == "/info" for path, _ in calls)


async def test_foreign_agent_and_main_wallet_keys_are_rejected(entropy, monkeypatch):
    markets, adapter, _, _ = entropy
    original = markets.entropy_info

    async def wrong_owner(kind, **payload):
        if kind == "userRole" and payload["user"] == adapter.key.address:
            return {"role": "agent", "data": {"user": "0x" + "33" * 20}}
        if kind == "userRole" and payload["user"] == Account.from_key("11" * 32).address:
            return {"role": "user"}
        return await original(kind, **payload)

    monkeypatch.setattr(markets, "entropy_info", wrong_owner)
    with pytest.raises(ValueError, match="未授权"):
        await adapter.validate()
    with pytest.raises(ValueError, match="未授权"):
        main_key = Entropy(
            adapter.value.model_copy(update={"api_private_key": SecretStr("11" * 32)}), markets
        )
        await main_key.validate()


async def test_entropy_native_precision_and_qualified_markets_are_not_aliased(entropy):
    markets, _, _, _ = entropy
    assert set(await markets.catalog(Provider.ENTROPY)) == {"BTC", "ETH", "HYPE", "io:BTC", "io:OAI"}
    btc = await markets.spec(Provider.ENTROPY, "BTC")
    eth = await markets.spec(Provider.ENTROPY, "ETH")
    assert btc.market_id == 0 and btc.quantity_step == Decimal("0.00001")
    assert bounded_price(Decimal("83578.35"), btc, "buy") == Decimal("83579")
    assert bounded_price(Decimal("2530.125"), eth, "sell") == Decimal("2530.1")
    assert bounded_price(Decimal("999.999"), eth, "buy") == Decimal("1000.0")
    assert bounded_price(Decimal("1234567.1"), btc, "sell") == Decimal("1234567")
    book = await markets.book(Provider.ENTROPY, "BTC")
    assert book.bids[0].price == Decimal("59999") and book.source.startswith("Entropy")


async def test_entropy_hip3_keeps_native_id_ticker_and_margin_domain(entropy):
    markets, adapter, data, calls = entropy
    spec = await markets.spec(Provider.ENTROPY, "io:OAI")
    assert spec.market_id == 120001 and spec.quantity_step == Decimal("0.001")
    value = intent().model_copy(update={"symbol": "io:OAI", "quantity": Decimal("0.1"), "limit_price": Decimal("1500")})
    prepared = await adapter.prepare(value)
    assert prepared["action"]["orders"][0]["a"] == 120001
    isolated = GridMarginCapital(investment_usd=100, leverage=3, margin_mode="isolated")
    assert (await adapter.prepare_margin("io:OAI", isolated))["action"]["asset"] == 120001
    with pytest.raises(ValueError, match="模式"):
        await adapter.prepare_margin("io:OAI", isolated.model_copy(update={"margin_mode": "cross"}))
    data["openOrders_io"] = [{"coin": "io:OAI", "oid": 99}]
    assert await adapter.open_orders("io:OAI") == data["openOrders_io"]
    assert calls[-1][1]["dex"] == "io"
    data["clearinghouseState_io"]["withdrawable"] = "20"
    data["clearinghouseState_io"]["marginSummary"]["accountValue"] = "50"
    data["clearinghouseState_io"]["assetPositions"] = [{"position": {
        "coin": "io:OAI", "szi": "0.1", "entryPx": "1500", "unrealizedPnl": "1"
    }}]
    data["userAbstraction"] = "default"
    snapshot = await adapter.snapshot()
    assert snapshot.positions[0].symbol == "io:OAI" and snapshot.equity == Decimal("1050.50")
    assert await adapter.available("io:OAI") == 20  # Native domain, not aggregate balance.
    data["userAbstraction"] = "dexAbstraction"
    assert await adapter.available("io:OAI") == Decimal("950.40")
    assert all(path == "/info" for path, _ in calls)


async def test_hip3_original_order_recovery_uses_qualified_coin(entropy):
    _, adapter, data, _ = entropy
    value = intent().model_copy(update={"symbol": "io:OAI"})
    data["orderStatus"]["order"]["order"]["coin"] = "io:OAI"
    data["userFillsByTime"][0]["coin"] = "io:OAI"
    assert (await adapter.lookup(value, "42")).quantity == value.quantity
    data["userFillsByTime"][0]["coin"] = "OAI"
    with pytest.raises(ValueError, match="身份"):
        await adapter.lookup(value, "42")


async def test_signed_ioc_uses_entropy_builder_without_added_fee_and_recovers_by_cloid(entropy):
    _, adapter, data, calls = entropy
    prepared = await adapter.prepare(intent())
    assert prepared["action"]["builder"] == {"b": ENTROPY_BUILDER, "f": 0}
    assert prepared["action"]["orders"][0]["t"] == {"limit": {"tif": "Ioc"}}
    assert prepared["vaultAddress"] is None and prepared["expiresAfter"] > prepared["nonce"]
    assert set(prepared["signature"]) == {"r", "s", "v"}
    assert await adapter.send(prepared) == "42"
    result = await adapter.lookup(intent(), None)  # Simulate lost ACK; use same client ID.
    assert result.status == "filled" and result.quantity == intent().quantity
    assert result.fee == Decimal("0.02699955") and result.average_price == Decimal("59999")
    assert sum(path == "/exchange" for path, _ in calls) == 1
    assert calls[-2][1]["oid"] == "0x" + intent().client_id
    data["userFillsByTime"] = []
    assert (await adapter.lookup(intent(), "42")).status == "unknown"


async def test_partial_cancel_unknown_fee_and_identity_mismatch_stay_explicit(entropy):
    _, adapter, data, _ = entropy
    row = data["orderStatus"]["order"]
    row["status"] = "canceled"
    row["order"]["sz"] = "0.0005"
    fill = data["userFillsByTime"][0]
    fill.update(sz="0.0005", feeToken="OTHER", fee="0.01")
    result = await adapter.lookup(intent(), "42")
    assert result.status == "canceled" and result.quantity == Decimal("0.0005") and result.fee is None
    row["order"]["sz"] = "0"
    assert (await adapter.lookup(intent(), "42")).status == "unknown"
    row["order"]["cloid"] = "0x" + "bb" * 16
    with pytest.raises(ValueError, match="身份"):
        await adapter.lookup(intent(), "42")


async def test_native_margin_is_signed_once_and_settings_read_from_account(entropy):
    _, adapter, _, calls = entropy
    margin = await adapter.margin("BTC")
    assert margin.leverage == 3 and margin.margin_mode == "isolated" and margin.max_leverage == 40
    assert margin.position_margin is None
    value = GridMarginCapital(investment_usd=100, leverage=3, margin_mode="isolated")
    prepared = await adapter.prepare_margin("BTC", value)
    assert prepared["action"] == {"type": "updateLeverage", "asset": 0, "isCross": False, "leverage": 3}
    await adapter.send_margin(prepared)
    assert sum(path == "/exchange" for path, _ in calls) == 1
    assert await adapter.open_orders("BTC") == []
    assert await adapter.open_orders("ETH") == [{"coin": "ETH", "oid": 9}]


@pytest.mark.parametrize("path,attempts", [("/info", 2), ("/exchange", 1)])
async def test_entropy_post_reads_retry_but_signed_writes_never_repeat(entropy, monkeypatch, path, attempts):
    markets, _, _, _ = entropy
    monkeypatch.setattr("perp_farming_bots.markets.READ_RETRY_DELAY_SECONDS", 0)
    count = []

    def disconnected(request):
        count.append(request)
        raise httpx.ConnectError("test outage", request=request)

    markets.http = httpx.AsyncClient(transport=httpx.MockTransport(disconnected))
    with pytest.raises(VenueRequestError):
        await markets.request(Provider.ENTROPY, "POST", path, json={"type": "test"})
    assert len(count) == attempts


def test_entropy_credentials_do_not_invent_native_account_indices():
    key = SecretStr("22" * 32)
    value = dict(name="Entropy", provider="entropy", address="0x" + "11" * 20, api_private_key=key)
    assert ConnectionCreate(**value).account_index is None
    for invalid in [dict(account_index=0), dict(api_key_index=0), dict(api_private_key=SecretStr("zz" * 32))]:
        with pytest.raises(ValidationError):
            ConnectionCreate(**(value | invalid))
    assert Account.from_key(key.get_secret_value()).address


async def test_entropy_connection_form_uses_address_without_numeric_account_indices(env, entropy, page, monkeypatch):
    import asyncio

    from nicegui import ui
    from test_account_form import click

    _, runtime, _, _ = env
    markets, _, _, calls = entropy
    monkeypatch.setattr(runtime.accounts, 'markets', markets)
    click(page, '连接账户')
    provider = next(e for e in page.elements.values() if isinstance(e, ui.select) and e.label == '交易所')
    provider.set_value('entropy')
    name = next(e for e in page.elements.values() if isinstance(e, ui.input) and e.label.startswith('账户昵称'))
    wallet = next(e for e in page.elements.values() if isinstance(e, ui.input) and e.label == '钱包地址')
    private_key = next(e for e in page.elements.values() if isinstance(e, ui.input) and e.label == 'API Signing Key')
    name.set_value('Entropy 1')
    wallet.set_value('0x' + '11' * 20)
    private_key.set_value('22' * 32)
    assert wallet.visible
    assert not any(e.visible for e in page.elements.values() if isinstance(e, ui.number) and e.label in ['Account Index', 'API key 编号'])
    await asyncio.gather(*click(page, '验证并连接账户'))
    connections = [c for c in runtime.store.connections() if c.provider == Provider.ENTROPY]
    assert len(connections) == 1
    assert connections[0].account_index is None and connections[0].account_ref == '0x' + '11' * 20
    assert private_key.value == ''
    assert all(path == '/info' for path, _ in calls)
    # The UI connected a read-validated account; it did not submit orders or wallet approvals.
