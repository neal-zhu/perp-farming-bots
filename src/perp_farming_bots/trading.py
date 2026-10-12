from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from typing import Any

import lighter
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .markets import HOSTS, Markets
from .models import AccountSnapshot, ConnectionCreate, NativePosition, OrderIntent, OrderResult, Provider
from .security import Secrets
from .store import Store

# Native SDK clients are selected by account/key indices. Recreate under one lock so
# equal indices on Core and Robinhood cannot accidentally use each other's chain/key.
SIGNER_LOCK = asyncio.Lock()
CHAIN_IDS = {Provider.LIGHTER: 304, Provider.LIGHTER_RH: 466324}


def exact_units(value: Decimal, step: Decimal) -> int:
    units = value / step
    if units != units.to_integral_value():
        raise ValueError("价格或数量不符合交易所精度")
    return int(units)


class Adapter:
    def __init__(self, value: ConnectionCreate, markets: Markets):
        self.value, self.markets = value, markets

    async def snapshot(self) -> AccountSnapshot:
        raise NotImplementedError

    async def validate(self) -> AccountSnapshot:
        raise NotImplementedError

    async def prepare(self, intent: OrderIntent) -> dict[str, Any]:
        raise NotImplementedError

    async def send(self, prepared: dict[str, Any]) -> str | None:
        raise NotImplementedError

    async def lookup(self, intent: OrderIntent, native_id: str | None) -> OrderResult:
        raise NotImplementedError

    async def open_orders(self, symbol: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def unknown(self, native_id: str | None = None) -> OrderResult:
        return OrderResult(status="unknown", quantity=None, average_price=None, fee=None, native_id=native_id)


class Arcus(Adapter):
    def __init__(self, value: ConnectionCreate, markets: Markets):
        super().__init__(value, markets)
        self.key = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(value.api_private_key.get_secret_value().removeprefix("0x"))
        )
        self.public_key = self.key.public_key().public_bytes_raw().hex()

    def params(self) -> dict[str, Any]:
        return {"address": self.value.address, "accountIndex": self.value.account_index}

    async def get(self, path: str, **params):
        return await self.markets.request(
            Provider.ARCUS,
            "GET",
            path,
            params={**self.params(), **params},
            headers={"X-API-Key": self.public_key},
        )

    async def validate(self) -> AccountSnapshot:
        response = await self.get("/v1/apiKeys")
        matched = [k for k in response["apiKeys"] if k["apiKey"].lower() == self.public_key]
        if len(matched) != 1:
            raise ValueError("Arcus API Signing Key 未登记到该钱包")
        key = matched[0]
        if key["address"].lower() != self.value.address or key["status"] != "ACTIVE":
            raise ValueError("Arcus API key 钱包或状态不匹配")
        if key["validUntil"] <= time.time() * 1000:
            raise ValueError("Arcus API key 已过期")
        if key.get("allSubaccounts") is not True and key.get("accountIndex") != self.value.account_index:
            raise ValueError("Arcus API key 的子账户范围不匹配")
        return await self.snapshot()

    async def snapshot(self) -> AccountSnapshot:
        r = await self.get("/v1/account")
        if r["address"].lower() != self.value.address or r["accountIndex"] != self.value.account_index:
            raise ValueError("Arcus 返回了不匹配的原生账户")
        positions = []
        for p in r["positions"].values():
            quantity = Decimal(p["size"])
            if quantity:
                positions.append(
                    NativePosition(
                        symbol=p["marketDisplayName"].removesuffix("-USD"),
                        quantity=quantity,
                        entry_price=Decimal(p["averageEntryPrice"]),
                        unrealized_pnl=Decimal(p["unrealizedPnl"]),
                    )
                )
        return AccountSnapshot(
            available=r["freeCollateral"],
            equity=r["equity"],
            positions=positions,
            received_at=time.time(),
            source="Arcus 原生账户",
        )

    async def prepare(self, intent: OrderIntent) -> dict[str, Any]:
        spec = await self.markets.spec(Provider.ARCUS, intent.symbol)
        timestamp = time.time_ns()
        good_til = timestamp // 1000 + 40 * 86400 * 1_000_000
        payload = {
            "ad": self.value.address,
            "ai": self.value.account_index,
            "c": intent.client_id,
            "ct": timestamp,
            "g": good_til * 1000,
            "m": spec.market_id,
            "op": 1,
            "p": exact_units(intent.limit_price, spec.price_tick),
            "q": exact_units(intent.quantity, spec.quantity_step),
            "r": int(intent.reduce_only),
            "s": 0 if intent.side == "buy" else 1,
            "t": 2,
            "v": 1,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return {
            "headers": {
                "X-API-Key": self.public_key,
                "X-Timestamp": str(timestamp),
                "X-Signature": self.key.sign(canonical).hex(),
            },
            "body": {
                **self.params(),
                "marketId": spec.market_id,
                "clientId": intent.client_id,
                "orderSide": intent.side.upper(),
                "orderType": "LIMIT",
                "timeInForce": "IOC",
                "quantity": str(intent.quantity),
                "price": str(intent.limit_price),
                "goodTilTime": str(good_til),
                "timestamp": timestamp,
                "reduceOnly": intent.reduce_only,
            },
        }

    async def send(self, prepared: dict[str, Any]) -> str | None:
        r = await self.markets.request(
            Provider.ARCUS,
            "POST",
            "/v1/placeOrder",
            params={"address": self.value.address},
            json=prepared["body"],
            headers=prepared["headers"],
        )
        return r.get("orderId")

    async def open_orders(self, symbol: str) -> list[dict[str, Any]]:
        spec = await self.markets.spec(Provider.ARCUS, symbol)
        r = await self.get("/v1/openOrders", market=str(spec.market_id))
        return r["orders"]

    async def lookup(self, intent: OrderIntent, native_id: str | None) -> OrderResult:
        spec = await self.markets.spec(Provider.ARCUS, intent.symbol)
        if native_id is not None:
            r = await self.get(f"/v1/order/{native_id}")
        else:
            response = await self.get("/v1/orders", market=str(spec.market_id), limit=500)
            matches = [o for o in response["orders"] if o.get("clientId") == intent.client_id]
            if len(matches) != 1:
                return self.unknown()
            r = matches[0]
        if (
            r.get("clientId") != intent.client_id
            or r["marketId"] != spec.market_id
            or r["side"] != intent.side.upper()
            or Decimal(r["originalSize"]) != intent.quantity
        ):
            raise ValueError("Arcus 订单身份与本地提交不符")
        status = r["status"].lower()
        if status not in {"filled", "canceled", "rejected"}:
            return self.unknown(r["orderId"])
        # originalSize - remainingSize is documented native cumulative filled size.
        quantity = Decimal(r["originalSize"]) - Decimal(r["remainingSize"])
        price = Decimal(r["avgFillPrice"]) if quantity > 0 and r.get("avgFillPrice") is not None else None
        fee = None
        if quantity > 0:
            evidence = await self.get("/v1/fills", market=str(spec.market_id), limit=500)
            matched = [f for f in evidence["fills"] if f["orderId"] == r["orderId"]]
            total = sum((Decimal(f["size"]) for f in matched), Decimal(0))
            if total == quantity:
                price = sum((Decimal(f["size"]) * Decimal(f["price"]) for f in matched), Decimal(0)) / total
                fee = sum((Decimal(f["fee"]) for f in matched), Decimal(0))
            if price is None:
                return self.unknown(r["orderId"])
        return OrderResult(
            status=status,
            quantity=quantity,
            average_price=price,
            fee=fee if quantity > 0 else Decimal(0),
            native_id=r["orderId"],
        )


class Lighter(Adapter):
    def __init__(self, value: ConnectionCreate, markets: Markets):
        super().__init__(value, markets)
        if value.api_key_index is None:
            raise ValueError("Lighter API key 编号缺失")
        self.key_index = value.api_key_index

    async def auth(self, *, check: bool = False) -> str:
        async with SIGNER_LOCK:
            signer = lighter.SignerClient(
                url=HOSTS[self.value.provider],
                chain_id=CHAIN_IDS[self.value.provider],
                account_index=self.value.account_index,
                api_private_keys={self.key_index: self.value.api_private_key.get_secret_value()},
            )
            try:
                if check:
                    error = await asyncio.wait_for(asyncio.to_thread(signer.check_client), timeout=15)
                    if error is not None:
                        raise ValueError("Lighter API key 未通过原生账户校验")
                token, error = signer.create_auth_token_with_expiry(api_key_index=self.key_index)
                if error is not None or token is None:
                    raise ValueError("Lighter API key 无法生成账户授权")
                return token
            finally:
                await signer.close()

    async def validate(self) -> AccountSnapshot:
        await self.auth(check=True)
        return await self.snapshot()

    async def snapshot(self) -> AccountSnapshot:
        r = await self.markets.request(
            self.value.provider,
            "GET",
            "/api/v1/account",
            params={"by": "index", "value": str(self.value.account_index)},
        )
        matches = [a for a in r["accounts"] if a["account_index"] == self.value.account_index]
        if len(matches) != 1:
            raise ValueError("Lighter 原生账户不存在或身份不匹配")
        a = matches[0]
        if self.value.address is not None and a["l1_address"].lower() != self.value.address:
            raise ValueError("Lighter 钱包地址与账户编号不匹配")
        positions = [
            NativePosition(
                symbol=p["symbol"],
                quantity=Decimal(p["position"]) * p["sign"],
                entry_price=Decimal(p["avg_entry_price"]),
                unrealized_pnl=Decimal(p["unrealized_pnl"]),
            )
            for p in a["positions"]
            if Decimal(p["position"]) != 0
        ]
        return AccountSnapshot(
            available=a["available_balance"],
            equity=a["collateral"],
            positions=positions,
            received_at=time.time(),
            source="Lighter 原生账户",
        )

    async def prepare(self, intent: OrderIntent) -> dict[str, Any]:
        spec = await self.markets.spec(self.value.provider, intent.symbol)
        nonce = await self.markets.request(
            self.value.provider,
            "GET",
            "/api/v1/nextNonce",
            params={"account_index": self.value.account_index, "api_key_index": self.value.api_key_index},
        )
        async with SIGNER_LOCK:
            signer = lighter.SignerClient(
                url=HOSTS[self.value.provider],
                chain_id=CHAIN_IDS[self.value.provider],
                account_index=self.value.account_index,
                api_private_keys={self.key_index: self.value.api_private_key.get_secret_value()},
            )
            try:
                tx_type, tx_info, tx_hash, error = signer.sign_create_order(
                    market_index=spec.market_id,
                    client_order_index=int(intent.client_id),
                    base_amount=exact_units(intent.quantity, spec.quantity_step),
                    price=exact_units(intent.limit_price, spec.price_tick),
                    is_ask=int(intent.side == "sell"),
                    order_type=signer.ORDER_TYPE_LIMIT,
                    time_in_force=signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                    order_expiry=signer.DEFAULT_IOC_EXPIRY,
                    reduce_only=int(intent.reduce_only),
                    nonce=nonce["nonce"],
                    api_key_index=self.key_index,
                )
                if error is not None or tx_info is None or tx_hash is None:
                    raise ValueError("Lighter 原生订单签名失败")
                return {"tx_type": tx_type, "tx_info": tx_info, "tx_hash": tx_hash, "nonce": nonce["nonce"]}
            finally:
                await signer.close()

    async def send(self, prepared: dict[str, Any]) -> str | None:
        await self.markets.request(
            self.value.provider,
            "POST",
            "/api/v1/sendTx",
            data={"tx_type": str(prepared["tx_type"]), "tx_info": prepared["tx_info"]},
        )
        return None  # A transaction hash is not an order id or evidence of a fill.

    async def open_orders(self, symbol: str) -> list[dict[str, Any]]:
        spec = await self.markets.spec(self.value.provider, symbol)
        r = await self.markets.request(
            self.value.provider,
            "GET",
            "/api/v1/accountActiveOrders",
            params={"account_index": self.value.account_index, "market_id": spec.market_id},
            headers={"authorization": await self.auth()},
        )
        return r["orders"]

    async def lookup(self, intent: OrderIntent, native_id: str | None) -> OrderResult:
        spec = await self.markets.spec(self.value.provider, intent.symbol)
        r = await self.markets.request(
            self.value.provider,
            "GET",
            "/api/v1/accountInactiveOrders",
            params={"account_index": self.value.account_index, "market_id": spec.market_id, "limit": 100},
            headers={"authorization": await self.auth()},
        )
        matches = [o for o in r["orders"] if o["client_order_index"] == int(intent.client_id)]
        if len(matches) != 1:
            return self.unknown(native_id)
        o = matches[0]
        if (
            o["owner_account_index"] != self.value.account_index
            or o["market_index"] != spec.market_id
            or bool(o["is_ask"]) != (intent.side == "sell")
            or Decimal(o["initial_base_amount"]) != intent.quantity
        ):
            raise ValueError("Lighter 订单身份与本地提交不符")
        status = o["status"]
        if status != "filled" and not status.startswith("canceled"):
            return self.unknown(o["order_id"])
        quantity = Decimal(o["filled_base_amount"])
        price = Decimal(o["filled_quote_amount"]) / quantity if quantity > 0 else None
        return OrderResult(
            status="filled" if status == "filled" else "canceled",
            quantity=quantity,
            average_price=price,
            fee=None if quantity > 0 else Decimal(0),
            native_id=o["order_id"],
        )


class Accounts:
    def __init__(self, store: Store, markets: Markets, secrets: Secrets):
        self.store, self.markets, self.secrets = store, markets, secrets
        self.adapters: dict[str, Adapter] = {}
        self.snapshots: dict[str, AccountSnapshot] = {}
        self.errors: dict[str, str] = {}

    def adapter_for(self, value: ConnectionCreate) -> Adapter:
        if value.provider == Provider.ARCUS:
            return Arcus(value, self.markets)
        if value.provider in CHAIN_IDS:
            return Lighter(value, self.markets)
        raise ValueError("该交易所的账户接入尚未完成")

    def adapter(self, connection_id: str) -> Adapter:
        if connection_id not in self.adapters:
            self.adapters[connection_id] = self.adapter_for(
                ConnectionCreate.model_validate_json(
                    self.secrets.decrypt(self.store.credentials(connection_id))
                )
            )
        return self.adapters[connection_id]

    async def add(self, value: ConnectionCreate):
        adapter = self.adapter_for(value)
        snapshot = await adapter.validate()
        # SecretStr is intentionally serialized only here, for encrypted local storage.
        record = value.model_dump(mode="json")
        record["api_private_key"] = value.api_private_key.get_secret_value()
        connection = self.store.add_connection(value, snapshot, self.secrets.encrypt(json.dumps(record)))
        self.adapters[connection.id] = adapter
        self.snapshots[connection.id] = snapshot
        return connection

    async def refresh(self, connection_id: str) -> AccountSnapshot:
        try:
            snapshot = await self.adapter(connection_id).snapshot()
        except Exception as exc:
            self.errors[connection_id] = str(exc) if isinstance(exc, ValueError) else "账户读取失败，请重试"
            raise ValueError(self.errors[connection_id]) from exc
        self.snapshots[connection_id] = snapshot
        self.errors.pop(connection_id, None)
        return snapshot

    def view(self, connection_id: str) -> dict[str, Any]:
        snapshot = self.snapshots.get(connection_id)
        return {
            "snapshot": snapshot.model_dump(mode="json") if snapshot is not None else None,
            "status": "unavailable"
            if connection_id in self.errors or snapshot is None
            else "stale"
            if time.time() - snapshot.received_at > 30
            else "connected",
            "error": self.errors.get(connection_id),
        }
