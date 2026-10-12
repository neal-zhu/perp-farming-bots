from __future__ import annotations

import asyncio
import math
import time
from decimal import Decimal
from typing import Any

import ccxt.async_support as ccxt
import lighter

from .models import Book, Level, Provider


class Markets:
    """Public data only. Demo data is an explicit provider, never an outage fallback."""

    def __init__(self) -> None:
        self.cache: dict[tuple[Provider, str], Book] = {}
        self.errors: dict[tuple[Provider, str], str] = {}
        self.catalogs: dict[Provider, dict[str, Any]] = {}
        self.clients: dict[Provider, Any] = {}
        self.locks: dict[tuple[Provider, str], asyncio.Lock] = {}

    async def close(self) -> None:
        for client in self.clients.values():
            await client.close()

    def client(self, provider: Provider) -> Any:
        if provider not in self.clients:
            if provider in {Provider.LIGHTER, Provider.LIGHTER_RH}:
                host = (
                    "https://api.rh.lighter.xyz"
                    if provider == Provider.LIGHTER_RH
                    else "https://mainnet.zklighter.elliot.ai"
                )
                self.clients[provider] = lighter.ApiClient(lighter.Configuration(host=host))
            elif provider == Provider.HYPERLIQUID:
                self.clients[provider] = ccxt.hyperliquid({"enableRateLimit": True})
            elif provider == Provider.BINANCE:
                self.clients[provider] = ccxt.binanceusdm({"enableRateLimit": True})
            else:
                raise ValueError("该场馆的公共行情接入尚未实现")
        return self.clients[provider]

    async def catalog(self, provider: Provider) -> list[str]:
        if provider in {Provider.DEMO_A, Provider.DEMO_B}:
            return ["BTC", "ETH", "SOL"]
        if provider == Provider.ARCUS:
            raise ValueError("Arcus adapter 仍在开发中；不会使用其他场馆行情代替")
        if provider not in self.catalogs:
            client = self.client(provider)
            if provider in {Provider.LIGHTER, Provider.LIGHTER_RH}:
                result = await asyncio.wait_for(
                    lighter.OrderApi(client).order_book_details(_request_timeout=10), timeout=12
                )
                if result.code != 200:
                    raise ValueError("Lighter 未返回成功的市场目录")
                self.catalogs[provider] = {
                    m.symbol: m.market_id
                    for m in result.order_book_details
                    if m.market_type == "perp" and m.status == "active"
                }
            else:
                native = await asyncio.wait_for(client.load_markets(), timeout=20)
                self.catalogs[provider] = {
                    m["base"]: m["symbol"]
                    for m in native.values()
                    if m.get("swap") is True
                    and m.get("linear") is True
                    and m.get("active") is not False
                    and m["quote"] in {"USDT", "USDC", "USD"}
                }
        return sorted(self.catalogs[provider])

    async def book(self, provider: Provider, symbol: str, *, refresh: bool = False) -> Book:
        key = (provider, symbol)
        cached = self.cache.get(key)
        if not refresh and cached is not None and cached.fresh(2):
            return cached
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self.cache.get(key)
            if not refresh and cached is not None and cached.fresh(2):
                return cached
            try:
                result = await self._fetch(provider, symbol)
            except Exception as exc:
                self.errors[key] = f"公共行情不可用（{type(exc).__name__}）；请稍后重试"
                raise ValueError(self.errors[key]) from exc
            self.cache[key] = result
            self.errors.pop(key, None)
            return result

    async def _fetch(self, provider: Provider, symbol: str) -> Book:
        if provider in {Provider.DEMO_A, Provider.DEMO_B}:
            bases = {"BTC": Decimal("60000"), "ETH": Decimal("2500"), "SOL": Decimal("150")}
            if symbol not in bases:
                raise ValueError("演示只支持 BTC、ETH、SOL")
            wave = Decimal(str(round(math.sin(time.time() / 30), 6))) * Decimal("0.0002")
            offset = Decimal("0.0025") if provider == Provider.DEMO_B else Decimal(0)
            mid = bases[symbol] * (1 + wave + offset)
            return Book(
                provider=provider,
                symbol=symbol,
                bids=[Level(price=mid * Decimal("0.9999"), quantity=Decimal("1000"))],
                asks=[Level(price=mid * Decimal("1.0001"), quantity=Decimal("1000"))],
                received_at=time.time(),
                source="虚构演示行情 · 模拟 USD",
            )
        await self.catalog(provider)
        if symbol not in self.catalogs[provider]:
            raise ValueError("此场馆没有所选的线性永续市场")
        client = self.client(provider)
        if provider in {Provider.LIGHTER, Provider.LIGHTER_RH}:
            result = await asyncio.wait_for(
                lighter.OrderApi(client).order_book_orders(
                    market_id=self.catalogs[provider][symbol], limit=20, _request_timeout=10
                ),
                timeout=12,
            )
            if result.code != 200:
                raise ValueError("Lighter 盘口返回非成功状态")
            bids = [(x.price, x.remaining_base_amount) for x in result.bids]
            asks = [(x.price, x.remaining_base_amount) for x in result.asks]
        else:
            native = await asyncio.wait_for(
                client.fetch_order_book(self.catalogs[provider][symbol], limit=20), timeout=15
            )
            bids, asks = native["bids"], native["asks"]
        bid_levels = sorted(
            (
                Level(price=Decimal(str(x[0])), quantity=Decimal(str(x[1])))
                for x in bids
                if Decimal(str(x[1])) > 0
            ),
            key=lambda x: x.price,
            reverse=True,
        )
        ask_levels = sorted(
            (
                Level(price=Decimal(str(x[0])), quantity=Decimal(str(x[1])))
                for x in asks
                if Decimal(str(x[1])) > 0
            ),
            key=lambda x: x.price,
        )
        return Book(
            provider=provider,
            symbol=symbol,
            bids=bid_levels,
            asks=ask_levels,
            received_at=time.time(),
            source="公共盘口 · 成交和费用仍为模拟；按名义 USD 计价",
        )
