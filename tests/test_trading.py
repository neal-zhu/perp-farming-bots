import json
import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from conftest import FixtureMarkets, connection_value
from pydantic import SecretStr

from perp_farming_bots.models import ConnectionCreate, OrderIntent, Provider
from perp_farming_bots.trading import Arcus, Lighter


def intent(*, client_id="CaseSensitiveClient", side="buy", reduce_only=False):
    return OrderIntent(
        connection_id="connection",
        symbol="BTC",
        side=side,
        quantity=Decimal("0.002"),
        limit_price=Decimal("60100"),
        reduce_only=reduce_only,
        client_id=client_id,
    )


async def test_arcus_signs_exact_typed_payload_with_nanoseconds_and_tick_units():
    markets = FixtureMarkets()
    adapter = Arcus(connection_value(), markets)
    order = intent(reduce_only=True)
    prepared = await adapter.prepare(order)
    body, headers = prepared["body"], prepared["headers"]
    timestamp = int(headers["X-Timestamp"])
    assert abs(time.time_ns() - timestamp) < 1_000_000_000
    assert body["timestamp"] == timestamp
    assert int(body["goodTilTime"]) * 1000 > timestamp + 31 * 86400 * 1_000_000_000
    assert body["timeInForce"] == "IOC" and body["reduceOnly"] is True
    payload = {
        "ad": connection_value().address,
        "ai": 0,
        "c": "CaseSensitiveClient",
        "ct": timestamp,
        "g": int(body["goodTilTime"]) * 1000,
        "m": 1,
        "op": 1,
        "p": 601000,
        "q": 2,
        "r": 1,
        "s": 0,
        "t": 2,
        "v": 1,
    }
    adapter.key.public_key().verify(
        bytes.fromhex(headers["X-Signature"]),
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
    )
    await markets.close()


async def test_arcus_ack_and_incomplete_fill_evidence_remain_unknown():
    markets = FixtureMarkets()
    adapter = Arcus(connection_value(), markets)
    order = intent()
    adapter.get = AsyncMock(
        return_value={
            "orders": [
                {
                    "clientId": order.client_id,
                    "marketId": 1,
                    "side": "BUY",
                    "originalSize": "0.002",
                    "status": "ACK",
                    "orderId": "native",
                }
            ]
        }
    )
    assert (await adapter.lookup(order, None)).status == "unknown"
    adapter.get = AsyncMock(
        side_effect=[
            {
                "clientId": order.client_id,
                "marketId": 1,
                "side": "BUY",
                "originalSize": "0.002",
                "remainingSize": "0.001",
                "status": "CANCELED",
                "orderId": "native",
            },
            {"fills": []},
        ]
    )
    assert (await adapter.lookup(order, "native")).quantity is None
    await markets.close()


async def test_arcus_fills_supply_actual_quantity_price_and_fee():
    markets = FixtureMarkets()
    adapter = Arcus(connection_value(), markets)
    order = intent()
    adapter.get = AsyncMock(
        side_effect=[
            {
                "clientId": order.client_id,
                "marketId": 1,
                "side": "BUY",
                "originalSize": "0.002",
                "remainingSize": "0.001",
                "status": "CANCELED",
                "orderId": "native",
            },
            {"fills": [{"orderId": "native", "size": "0.001", "price": "60000", "fee": "0.03"}]},
        ]
    )
    result = await adapter.lookup(order, "native")
    assert result.quantity == Decimal("0.001")
    assert result.average_price == Decimal("60000")
    assert result.fee == Decimal("0.03")
    await markets.close()


@pytest.mark.parametrize("provider,chain_id", [(Provider.LIGHTER, 304), (Provider.LIGHTER_RH, 466324)])
async def test_lighter_prepares_without_send_and_uses_explicit_chain_nonce_and_ioc(
    monkeypatch, provider, chain_id
):
    calls = []

    class Signer:
        ORDER_TYPE_LIMIT = 0
        ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL = 0
        DEFAULT_IOC_EXPIRY = 0

        def __init__(self, **kwargs):
            calls.append(("client", kwargs))

        def sign_create_order(self, **kwargs):
            calls.append(("sign", kwargs))
            return 14, "signed-transaction", "transaction-hash", None

        async def close(self):
            pass

    monkeypatch.setattr("perp_farming_bots.trading.lighter.SignerClient", Signer)
    markets = FixtureMarkets()
    markets.request = AsyncMock(return_value={"code": 200, "nonce": 42})
    adapter = Lighter(
        ConnectionCreate(
            name="account",
            provider=provider,
            account_index=123,
            api_key_index=2,
            api_private_key=SecretStr("33" * 32),
        ),
        markets,
    )
    prepared = await adapter.prepare(intent(client_id="456", side="sell", reduce_only=True))
    assert prepared["tx_hash"] == "transaction-hash"
    assert calls[0][1]["chain_id"] == chain_id
    assert calls[1][1]["nonce"] == 42
    assert calls[1][1]["client_order_index"] == 456
    assert calls[1][1]["reduce_only"] == 1
    assert calls[1][1]["base_amount"] == 2
    assert calls[1][1]["is_ask"] == 1
    assert calls[1][1]["order_expiry"] == 0
    assert markets.request.await_count == 1
    await markets.close()


async def test_lighter_terminal_lookup_keeps_unknown_fees_explicit():
    markets = FixtureMarkets()
    markets.request = AsyncMock(
        return_value={
            "code": 200,
            "orders": [
                {
                    "client_order_index": 456,
                    "owner_account_index": 123,
                    "market_index": 1,
                    "is_ask": False,
                    "initial_base_amount": "0.002",
                    "status": "canceled",
                    "filled_base_amount": "0.001",
                    "filled_quote_amount": "60",
                    "order_id": "native",
                }
            ],
        }
    )
    adapter = Lighter(
        ConnectionCreate(
            name="account",
            provider=Provider.LIGHTER_RH,
            account_index=123,
            api_key_index=2,
            api_private_key=SecretStr("33" * 32),
        ),
        markets,
    )
    adapter.auth = AsyncMock(return_value="test-token")
    result = await adapter.lookup(intent(client_id="456"), None)
    assert result.quantity == Decimal("0.001")
    assert result.average_price == Decimal("60000")
    assert result.fee is None
    await markets.close()


async def test_lighter_send_uses_official_form_encoded_fields():
    markets = FixtureMarkets()
    markets.request = AsyncMock(return_value={"code": 200, "tx_hash": "hash"})
    adapter = Lighter(
        ConnectionCreate(
            name="account",
            provider=Provider.LIGHTER_RH,
            account_index=123,
            api_key_index=2,
            api_private_key=SecretStr("33" * 32),
        ),
        markets,
    )
    assert await adapter.send({"tx_type": 14, "tx_info": "signed", "tx_hash": "hash"}) is None
    markets.request.assert_awaited_once_with(
        Provider.LIGHTER_RH, "POST", "/api/v1/sendTx", data={"tx_type": "14", "tx_info": "signed"}
    )
    await markets.close()
