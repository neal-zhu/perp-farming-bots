"""Test-only exchange doubles. No test venue is available in the application."""

import time
from decimal import Decimal

import pytest
from pydantic import SecretStr

from perp_farming_bots.markets import Markets
from perp_farming_bots.models import (
    AccountSnapshot,
    Book,
    ConnectionCreate,
    FundingSnapshot,
    Level,
    MarketSpec,
    NativePosition,
    OrderIntent,
    OrderResult,
    Provider,
)
from perp_farming_bots.runtime import Runtime
from perp_farming_bots.security import Secrets
from perp_farming_bots.store import Store
from perp_farming_bots.trading import Accounts, Adapter


class FixtureMarkets(Markets):
    def __init__(self):
        super().__init__()
        self.stale = False

    async def funding(self, provider, symbol):
        return FundingSnapshot(
            provider=provider,
            symbol=symbol,
            status="available",
            predicted_rate_pct=Decimal("0.0012"),
            last_rate_pct=Decimal("0.0010"),
            interval_seconds=3600,
            next_payment_at=time.time() + 600,
            received_at=time.time(),
            source="test fixture",
            unavailable_reason=None,
        )

    async def spec(self, provider, symbol):
        return MarketSpec(
            provider=provider,
            symbol=symbol,
            native_symbol=symbol,
            market_id=1,
            quantity_step=Decimal("0.001"),
            price_tick=Decimal("0.1"),
            min_quantity=Decimal("0.001"),
            min_notional=Decimal("5"),
        )

    async def book(self, provider, symbol, *, refresh=False):
        return Book(
            provider=provider,
            symbol=symbol,
            bids=[Level(price=Decimal("60000"), quantity=Decimal("10"))],
            asks=[Level(price=Decimal("60001"), quantity=Decimal("10"))],
            received_at=time.time() - (60 if self.stale else 0),
            source="test fixture",
        )


class FixtureAdapter(Adapter):
    def __init__(self, value, markets):
        super().__init__(value, markets)
        self.net = Decimal(0)
        self.sent: list[OrderIntent] = []
        self.results: dict[str, OrderResult] = {}
        self.fraction = Decimal(1)
        self.unknown = False
        self.raise_after_send = False
        self.external_orders = []

    async def validate(self):
        return await self.snapshot()

    async def snapshot(self):
        positions = (
            [
                NativePosition(
                    symbol="BTC", quantity=self.net, entry_price=Decimal("60000"), unrealized_pnl=Decimal(0)
                )
            ]
            if self.net
            else []
        )
        return AccountSnapshot(
            available=Decimal("10000"),
            equity=Decimal("10000"),
            positions=positions,
            received_at=time.time(),
            source="test fixture",
        )

    async def prepare(self, intent):
        return {"intent": intent.model_dump(mode="json")}

    async def send(self, prepared):
        intent = OrderIntent.model_validate(prepared["intent"])
        self.sent.append(intent)
        quantity = intent.quantity * self.fraction
        self.net += quantity * (1 if intent.side == "buy" else -1)
        self.results[intent.client_id] = OrderResult(
            status="filled" if self.fraction == 1 else "canceled",
            quantity=quantity,
            average_price=Decimal("60000") if quantity > 0 else None,
            fee=Decimal("1") if quantity > 0 else Decimal(0),
            native_id=intent.client_id,
        )
        if self.raise_after_send:
            raise TimeoutError("lost acknowledgement")
        return intent.client_id

    async def lookup(self, intent, native_id):
        if self.unknown:
            return self.unknown_result(native_id)
        return self.results.get(intent.client_id, self.unknown_result(native_id))

    def unknown_result(self, native_id):
        return OrderResult(status="unknown", quantity=None, average_price=None, fee=None, native_id=native_id)

    async def open_orders(self, symbol):
        return self.external_orders


class FixtureAccounts(Accounts):
    def adapter_for(self, value):
        return FixtureAdapter(value, self.markets)


def connection_value(index=0, name=None):
    return ConnectionCreate(
        name=name or f"account {index}",
        provider=Provider.ARCUS,
        address="0x" + "11" * 20,
        account_index=index,
        api_private_key=SecretStr("22" * 32),
    )


@pytest.fixture
async def env(tmp_path):
    store = Store(tmp_path / "live.db")
    markets = FixtureMarkets()
    accounts = FixtureAccounts(store, markets, Secrets(tmp_path))
    a = await accounts.add(connection_value(0))
    b = await accounts.add(connection_value(1))
    runtime = Runtime(store, markets, accounts)
    yield store, runtime, a, b
    await runtime.stop()
    store.close()
