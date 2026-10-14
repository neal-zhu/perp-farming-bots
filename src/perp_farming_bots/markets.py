from __future__ import annotations

import asyncio
import json
import logging
import math
import ssl
import time
from decimal import Decimal
from typing import Any

import httpx
import truststore
from pydantic import ValidationError
from websockets.asyncio.client import connect

from .models import PROVIDER_NAMES, Book, FundingSnapshot, Level, MarketSpec, Provider

HOSTS = {
    Provider.ARCUS: "https://api.arcus.xyz",
    Provider.ENTROPY: "https://api.hyperliquid.xyz",
    Provider.LIGHTER: "https://mainnet.zklighter.elliot.ai",
    Provider.LIGHTER_RH: "https://api.rh.lighter.xyz",
}
READ_TOTAL_TIMEOUT_SECONDS = 20
READ_RETRY_DELAY_SECONDS = 0.5
READ_RETRY_STATUSES = {502, 503, 504}
logger = logging.getLogger(__name__)


class VenueRequestError(ValueError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

    @property
    def retryable_read(self) -> bool:
        return self.status_code is None or self.status_code in {404, 408, 425, 429} or self.status_code >= 500


class QuoteUnavailable(ValueError):
    """A quote read failed; this says nothing about an order's execution."""


def require_fresh_book(book: Book, max_age: float = 15) -> None:
    now = time.time()
    age = now - book.received_at
    if math.isfinite(age) and 0 <= age <= max_age:
        return
    logger.warning(
        "book_freshness_rejected provider=%s symbol=%s age_seconds=%.6f max_age_seconds=%g venue_at=%.6f local_at=%.6f",
        book.provider.value,
        book.symbol,
        age,
        max_age,
        book.received_at,
        now,
    )
    reason = (
        "盘口时间戳无效"
        if not math.isfinite(age)
        else "盘口时间戳超前"
        if age < 0
        else f"盘口已超过 {max_age:g} 秒时效（数据年龄 {age:.1f} 秒）"
    )
    raise QuoteUnavailable(f"{book.symbol} {reason}")


class Markets:
    """Native public REST books and market precision. No generated market data."""

    def __init__(self) -> None:
        self.http = httpx.AsyncClient(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), timeout=15)
        self.cache: dict[tuple[Provider, str], Book] = {}
        self.catalogs: dict[Provider, dict[str, MarketSpec]] = {}
        self.locks: dict[tuple[Provider, str], asyncio.Lock] = {}
        self.funding_cache: dict[tuple[Provider, str], FundingSnapshot] = {}
        self.funding_locks: dict[tuple[Provider, str], asyncio.Lock] = {}
        self.funding_checked: dict[tuple[Provider, str], float] = {}

    async def close(self) -> None:
        await self.http.aclose()

    def log_failure(
        self, provider: Provider, method: str, path: str, attempts: int, started: float, exc: Exception
    ) -> None:
        # Log endpoint names and exception classes, never native identifiers,
        # query parameters, auth headers, signed bodies or raw native errors.
        endpoint = "/".join(path.split("?", 1)[0].split("/")[: 3 if provider == Provider.ARCUS else 4])
        causes = []
        cause: BaseException | None = exc
        while cause is not None:
            causes.append(type(cause).__name__)
            cause = cause.__cause__
        logger.warning(
            "venue_request_failed provider=%s method=%s endpoint=%s attempts=%d elapsed_ms=%d status=%s causes=%s",
            provider.value,
            method,
            endpoint,
            attempts,
            (time.monotonic() - started) * 1000,
            exc.status_code if isinstance(exc, VenueRequestError) else None,
            "/".join(causes),
        )

    async def request_response(self, provider: Provider, method: str, path: str, **kwargs) -> httpx.Response:
        if provider not in HOSTS:
            raise ValueError("该交易所接入尚未完成")
        method = method.upper()
        read = method == "GET" or (provider == Provider.ENTROPY and method == "POST" and path == "/info")
        attempts = 0
        started = time.monotonic()
        first_failure = ""
        try:
            # Only reads may repeat. Writes preserve their original single-send
            # behavior; the execution journal handles uncertain acknowledgements.
            async with asyncio.timeout(READ_TOTAL_TIMEOUT_SECONDS if read else None):
                for attempt in range(2 if read else 1):
                    attempts += 1
                    try:
                        response = await self.http.request(method, HOSTS[provider] + path, **kwargs)
                    except httpx.TransportError as exc:
                        if read and attempt == 0:
                            first_failure = type(exc).__name__
                            await asyncio.sleep(READ_RETRY_DELAY_SECONDS)
                            continue
                        raise
                    if response.status_code >= 400:
                        if read and attempt == 0 and response.status_code in READ_RETRY_STATUSES:
                            first_failure = f"HTTP{response.status_code}"
                            await response.aclose()
                            await asyncio.sleep(READ_RETRY_DELAY_SECONDS)
                            continue
                        raise VenueRequestError(
                            f"{PROVIDER_NAMES[provider]} 请求失败（HTTP {response.status_code}）",
                            response.status_code,
                        )
                    if attempts > 1:
                        endpoint = "/".join(
                            path.split("?", 1)[0].split("/")[: 3 if provider == Provider.ARCUS else 4]
                        )
                        logger.info(
                            "venue_read_recovered provider=%s endpoint=%s attempts=%d first_failure=%s",
                            provider.value,
                            endpoint,
                            attempts,
                            first_failure,
                        )
                    return response
        except httpx.HTTPError as exc:
            self.log_failure(provider, method, path, attempts, started, exc)
            raise VenueRequestError(
                f"{PROVIDER_NAMES[provider]} 网络连接失败（{type(exc).__name__}）"
            ) from exc
        except TimeoutError as exc:
            self.log_failure(provider, method, path, attempts, started, exc)
            raise VenueRequestError(
                f"{PROVIDER_NAMES[provider]} 网络读取超时（总时限 {READ_TOTAL_TIMEOUT_SECONDS:g} 秒）"
            ) from exc
        except VenueRequestError as exc:
            self.log_failure(provider, method, path, attempts, started, exc)
            raise
        raise RuntimeError("网络读取未产生明确结果")

    async def request(self, provider: Provider, method: str, path: str, **kwargs) -> Any:
        response = await self.request_response(provider, method, path, **kwargs)
        result = response.json()
        if provider in {Provider.LIGHTER, Provider.LIGHTER_RH} and result.get("code") != 200:
            raise ValueError(f"{PROVIDER_NAMES[provider]} 返回非成功状态")
        return result

    async def entropy_info(self, kind: str, **payload) -> Any:
        return await self.request(Provider.ENTROPY, "POST", "/info", json={"type": kind, **payload})

    async def catalog(self, provider: Provider) -> list[str]:
        if provider not in self.catalogs:
            catalog: dict[str, MarketSpec] = {}
            if provider == Provider.ENTROPY:
                from .entropy import entropy_catalog

                catalog = await entropy_catalog(self)
            elif provider == Provider.ARCUS:
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
        try:
            async with self.locks.setdefault(key, asyncio.Lock()):
                spec = await self.spec(provider, symbol)
                if provider == Provider.ENTROPY:
                    r = await self.entropy_info("l2Book", coin=spec.native_symbol)
                    if r["coin"] != spec.native_symbol:
                        raise ValueError("Entropy 盘口市场身份不匹配")
                    bids = [(x["px"], x["sz"]) for x in r["levels"][0]]
                    asks = [(x["px"], x["sz"]) for x in r["levels"][1]]
                    received_at = r["time"] / 1000
                elif provider == Provider.ARCUS:
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
        except VenueRequestError as exc:
            if exc.status_code is None or exc.status_code in {408, 425, 429} or exc.status_code >= 500:
                raise QuoteUnavailable(f"{symbol} 盘口获取暂时失败：{exc}") from exc
            raise

    async def _funding_data(self, provider: Provider, spec: MarketSpec) -> dict[str, Any]:
        if provider == Provider.ENTROPY:
            from .entropy import entropy_funding

            return await entropy_funding(self, spec)
        if provider == Provider.ARCUS:
            response = await self.request(provider, "GET", "/v1/markets")
            matches = [m for m in response["markets"] if m["marketId"] == spec.market_id]
            if len(matches) != 1 or matches[0]["baseAsset"] != spec.symbol:
                raise ValueError("资金费率市场身份不匹配")
            m = matches[0]
            return {
                "predicted_rate_pct": Decimal(m["nextFundingRate"]) * 100,
                "last_rate_pct": Decimal(m["fundingRate"]) * 100,
                "next_payment_at": m["nextFundingAt"],
            }
        # A short read-only subscription gives the native hourly estimate. The
        # REST funding-rates comparison feed has different rate semantics.
        url = HOSTS[provider].replace("https://", "wss://") + "/stream?readonly=true"
        async with asyncio.timeout(10):
            async with connect(
                url, ssl=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), open_timeout=8, close_timeout=1
            ) as ws:
                await ws.send(json.dumps({"type": "subscribe", "channel": f"market_stats/{spec.market_id}"}))
                async for raw in ws:
                    response = json.loads(raw)
                    if response.get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                    if response.get("channel") != f"market_stats:{spec.market_id}":
                        continue
                    m = response["market_stats"]
                    if m["market_id"] != spec.market_id or m["symbol"] != spec.symbol:
                        raise ValueError("资金费率市场身份不匹配")
                    age = time.time() - response["timestamp"] / 1000
                    # Native Core/RH clocks can lead the receiving host slightly.
                    # Allow at most 5 seconds of clock skew, never an unbounded
                    # future timestamp or a snapshot older than 60 seconds.
                    if age < -5:
                        raise ValueError("资金费率时间戳异常：交易所时间领先本机超过 5 秒")
                    if not age <= 60:
                        raise ValueError("资金费率数据已过期")
                    # Lighter's native market_stats rates are percentage points.
                    next_payment = (m["funding_timestamp"] // 1000) + 3600
                    return {
                        "predicted_rate_pct": Decimal(m["current_funding_rate"]),
                        "last_rate_pct": Decimal(m["funding_rate"]),
                        "next_payment_at": next_payment,
                    }
        raise ValueError("资金费率连接提前关闭")

    async def funding(self, provider: Provider, symbol: str) -> FundingSnapshot:
        key = provider, symbol
        async with self.funding_locks.setdefault(key, asyncio.Lock()):
            cached = self.funding_cache.get(key)
            if cached is not None and time.time() - self.funding_checked[key] < 30:
                if cached.status == "unavailable" or (
                    cached.next_payment_at is not None and cached.next_payment_at > time.time()
                ):
                    return cached
            source = f"{PROVIDER_NAMES[provider]} 官方资金费率"
            try:
                spec = await self.spec(provider, symbol)
                data = await self._funding_data(provider, spec)
                if not time.time() < data["next_payment_at"] <= time.time() + 3660:
                    raise ValueError("资金费率结算时间已过期或无效")
                result = FundingSnapshot(
                    provider=provider,
                    symbol=symbol,
                    status="available",
                    interval_seconds=3600,
                    received_at=time.time(),
                    source=source,
                    unavailable_reason=None,
                    **data,
                )
            except Exception as exc:
                result = FundingSnapshot(
                    provider=provider,
                    symbol=symbol,
                    status="unavailable",
                    predicted_rate_pct=None,
                    last_rate_pct=None,
                    interval_seconds=3600,
                    next_payment_at=None,
                    received_at=None,
                    source=source,
                    unavailable_reason=str(exc)
                    if isinstance(exc, ValueError) and not isinstance(exc, ValidationError)
                    else "资金费率读取失败，请稍后重试",
                )
            self.funding_cache[key] = result
            self.funding_checked[key] = time.time()
            return result
