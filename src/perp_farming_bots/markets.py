from __future__ import annotations

import asyncio
import ssl
import time
from decimal import Decimal
from typing import Any

import httpx
import truststore

from .models import PROVIDER_NAMES, Book, Level, MarketSpec, Provider

HOSTS = {
    Provider.ARCUS: "https://api.arcus.xyz",
    Provider.LIGHTER: "https://mainnet.zklighter.elliot.ai",
    Provider.LIGHTER_RH: "https://api.rh.lighter.xyz",
}


class Markets:
    """Native public REST books and market precision. No generated market data."""

    def __init__(self) -> None:
        self.http = httpx.AsyncClient(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), timeout=15)
        self.cache: dict[tuple[Provider, str], Book] = {}
        self.catalogs: dict[Provider, dict[str, MarketSpec]] = {}
        self.locks: dict[tuple[Provider, str], asyncio.Lock] = {}

    async def close(self) -> None:
        await self.http.aclose()

    async def request(self, provider: Provider, method: str, path: str, **kwargs) -> Any:
        if provider not in HOSTS:
            raise ValueError("该交易所接入尚未完成")
        try:
            response = await self.http.request(method, HOSTS[provider] + path, **kwargs)
        except httpx.HTTPError as exc:
            raise ValueError(f"{PROVIDER_NAMES[provider]} 网络连接失败（{type(exc).__name__}）") from exc
        if response.status_code >= 400:
            # Do not expose raw responses which may echo signed requests or credentials.
            raise ValueError(f"{PROVIDER_NAMES[provider]} 请求失败（HTTP {response.status_code}）")
        result = response.json()
        if provider != Provider.ARCUS and result.get("code") != 200:
            raise ValueError(f"{PROVIDER_NAMES[provider]} 返回非成功状态")
        return result

    async def catalog(self, provider: Provider) -> list[str]:
        if provider not in self.catalogs:
            catalog: dict[str, MarketSpec] = {}
            if provider == Provider.ARCUS:
                response = await self.request(provider, "GET", "/v1/markets")
                for m in response["markets"]:
                    if m["type"] != "PERPETUAL" or m["status"] != "ONLINE" or m["category"] != "CRYPTO":
                        continue
                    symbol = m["baseAsset"]
                    if symbol in catalog:
                        raise ValueError("市场目录存在重名合约，请核实原生身份")
                    catalog[symbol] = MarketSpec(
                        provider=provider,
                        symbol=symbol,
                        market_id=m["marketId"],
                        native_symbol=m["marketDisplayName"],
                        quantity_step=Decimal(m["stepSize"]),
                        price_tick=Decimal(m["tickSize"]),
                        min_quantity=Decimal(m["minOrderSize"]),
                        min_notional=Decimal(m["minOrderNotional"]),
                        tick_tiers=m["tickTiers"],
                    )
            else:
                response = await self.request(provider, "GET", "/api/v1/orderBookDetails")
                for m in response["order_book_details"]:
                    if m["market_type"] != "perp" or m["status"] != "active":
                        continue
                    symbol = m["symbol"]
                    if symbol in catalog:
                        raise ValueError("市场目录存在重名合约")
                    if Decimal(str(m["multiplier"])) != 1:
                        continue
                    catalog[symbol] = MarketSpec(
                        provider=provider,
                        symbol=symbol,
                        market_id=m["market_id"],
                        native_symbol=m["symbol"],
                        quantity_step=Decimal(10) ** -m["supported_size_decimals"],
                        price_tick=Decimal(10) ** -m["supported_price_decimals"],
                        min_quantity=Decimal(m["min_base_amount"]),
                        min_notional=Decimal(m["min_quote_amount"]),
                    )
            self.catalogs[provider] = catalog
        return sorted(self.catalogs[provider])

    async def spec(self, provider: Provider, symbol: str) -> MarketSpec:
        await self.catalog(provider)
        if symbol not in self.catalogs[provider]:
            raise ValueError("此交易所没有所选永续市场")
        return self.catalogs[provider][symbol]

    async def book(self, provider: Provider, symbol: str, *, refresh: bool = False) -> Book:
        key = provider, symbol
        cached = self.cache.get(key)
        if not refresh and cached is not None and cached.fresh(2):
            return cached
        async with self.locks.setdefault(key, asyncio.Lock()):
            spec = await self.spec(provider, symbol)
            if provider == Provider.ARCUS:
                r = await self.request(
                    provider, "GET", f"/v1/l2OrderBook/{spec.native_symbol}", params={"nLevels": 20}
                )
                bids, asks = r["bids"], r["asks"]
                received_at = r["timestamp"] / 1_000_000
            else:
                r = await self.request(
                    provider,
                    "GET",
                    "/api/v1/orderBookOrders",
                    params={"market_id": spec.market_id, "limit": 20},
                )
                bids = [(x["price"], x["remaining_base_amount"]) for x in r["bids"]]
                asks = [(x["price"], x["remaining_base_amount"]) for x in r["asks"]]
                received_at = time.time()
            book = Book(
                provider=provider,
                symbol=symbol,
                bids=sorted(
                    [Level(price=x[0], quantity=x[1]) for x in bids if Decimal(x[1]) > 0],
                    key=lambda x: x.price,
                    reverse=True,
                ),
                asks=sorted(
                    [Level(price=x[0], quantity=x[1]) for x in asks if Decimal(x[1]) > 0],
                    key=lambda x: x.price,
                ),
                received_at=received_at,
                source=f"{PROVIDER_NAMES[provider]} 官方盘口",
            )
            self.cache[key] = book
            return book
