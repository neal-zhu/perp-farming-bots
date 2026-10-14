"""Ondo Perps native HMAC API, independent of wallet login and builder SDK flows."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlencode

from .markets import Markets, VenueRequestError
from .models import (
    AccountSnapshot,
    GridMarginCapital,
    MarginSnapshot,
    MarketSpec,
    NativePosition,
    OrderIntent,
    OrderResult,
    Provider,
)
from .trading import Adapter, OrderRejected, exact_units


class OndoRequestError(VenueRequestError):
    def __init__(self, status: int, code: str | None):
        self.code = code
        reasons = {
            "timestamp_too_far": "签名时间与交易所不符，请检查服务器时钟",
            "key_doesnt_have_scope": "API Key 缺少交易权限",
            "ip_not_permitted": "服务器 IP 不在 API Key 白名单中",
            "api_key_not_found": "API Key 不存在或已撤销",
            "signature_mismatch": "API Key 签名校验失败",
            "order_not_found": "原订单暂未返回，成交状态仍待确认",
        }
        super().__init__("Ondo Perps：" + reasons.get(code or "", f"请求失败（HTTP {status}）"), status)


def number(value: Any) -> Decimal:
    if not isinstance(value, str) or not value:
        raise ValueError("Ondo 原生金额缺失或格式无效")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("Ondo 原生金额格式无效") from None
    if not result.is_finite():
        raise ValueError("Ondo 原生金额无效")
    return result


def timestamp(value: Any) -> float:
    if not isinstance(value, str):
        raise ValueError("Ondo 原生时间缺失")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Ondo 原生时间没有时区")
    return parsed.timestamp()


def identity(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("Ondo 原生身份无效")
    return value


async def ondo_request(markets: Markets, method: str, path: str, **kwargs) -> dict[str, Any]:
    response = await markets.request_response(Provider.ONDO, method, path, raise_status=False, **kwargs)
    try:
        data = json.loads(response.text, parse_float=Decimal)
    except ValueError:
        raise VenueRequestError("Ondo 官方响应格式无效", response.status_code) from None
    if not isinstance(data, dict):
        raise ValueError("Ondo 官方响应不是对象")
    if response.status_code != 200 or data.get("success") is not True:
        code = data.get("error_code")
        raise OndoRequestError(response.status_code, code if isinstance(code, str) else None)
    return data


async def ondo_catalog(markets: Markets) -> dict[str, MarketSpec]:
    config, contracts = await asyncio.gather(
        ondo_request(markets, "GET", "/v1/markets"),
        ondo_request(markets, "GET", "/v1/perps/contracts"),
    )
    active: set[str] = set()
    for row in contracts["result"]:
        if (
            row["productType"] != "perpetual"
            or row["contractType"] != "linear"
            or row["disabled"] is not False
        ):
            continue
        symbol = row["market"]
        if row["quoteCurrency"] not in {"USD", "USDC"}:
            raise ValueError("Ondo 当前金额模型需要 USD 计价的永续市场")
        if symbol in active:
            raise ValueError("Ondo 市场目录存在重名合约")
        active.add(symbol)
    result = {}
    for row in config["result"]["perps"]["tradingPairs"]:
        symbol = row["market"]
        if symbol not in active:
            continue
        if symbol in result:
            raise ValueError("Ondo 市场配置存在重名合约")
        brackets = row["marginInfo"]
        if not brackets:
            raise ValueError("Ondo 原生杠杆上限缺失")
        # Native first-bracket maximum; position-dependent acceptance remains
        # subject to the venue's margin and position-size constraints.
        maximum = number(brackets[0]["maxLeverage"])
        step = number(row["baseIncrement"])
        result[symbol] = MarketSpec(
            provider=Provider.ONDO,
            symbol=symbol,
            native_symbol=symbol,
            market_id=symbol,
            quantity_step=step,
            price_tick=number(row["quoteIncrement"]),
            min_quantity=step,
            min_notional=None,
            max_leverage=maximum,
        )
    if active - result.keys():
        raise ValueError("Ondo 活跃合约缺少精度配置")
    return result


async def ondo_funding(markets: Markets, spec: MarketSpec) -> dict[str, Any]:
    current, history = await asyncio.gather(
        ondo_request(markets, "GET", "/v1/perps/funding_rates", params={"market": spec.native_symbol}),
        ondo_request(
            markets,
            "GET",
            "/v1/perps/funding_rate_history",
            params={"market": spec.native_symbol, "limit": 1},
        ),
    )
    estimate = current["result"]
    rows = history["result"]
    if not rows or estimate["market"] != spec.native_symbol or rows[0]["market"] != spec.native_symbol:
        raise ValueError("Ondo 资金费率市场身份或历史数据无效")
    if not 0 <= time.time() - timestamp(rows[0]["time"]) <= 7200:
        raise ValueError("Ondo 上次结算数据已过期")
    return {
        "predicted_rate_pct": number(estimate["rate"]) * 100,
        "last_rate_pct": number(rows[0]["fundingRate"]) * 100,
        "next_payment_at": timestamp(estimate["intervalEnds"]),
    }


# Exact POST /orders native validation rejections, not transport failures,
# duplicate identities, delayed routes, redirects or unexpected business errors.
ORDER_REJECTIONS = {
    "account_in_liquidation",
    "insufficient_funds",
    "insufficient_liquidity",
    "insufficient_margin",
    "invalid_market",
    "invalid_order_type",
    "invalid_time_in_force",
    "net_position_too_large",
    "order_invalid_price",
    "order_invalid_size",
    "order_matches_against_self",
    "order_negative_price",
    "order_negative_size",
    "order_price_outside_min_max_bounds",
    "order_price_outside_safe_bounds",
    "post_only_has_match",
    "price_over_ui_limit_10MM",
    "reduce_only_flipping_position",
    "reduce_only_increasing_position",
    "reduce_only_invalid_tif",
    "reduce_only_no_open_position",
    "too_many_open_orders",
    "trading_disabled",
}


class Ondo(Adapter):
    def signed(self, method: str, path: str, body: str = "") -> dict[str, Any]:
        if self.value.api_key_id is None:
            raise ValueError("Ondo API Key ID 缺失")
        stamp = str(int(time.time() * 1000))
        signature = hmac.new(
            self.value.api_private_key.get_secret_value().encode(),
            (stamp + method + path + body).encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "method": method,
            "path": path,
            "body": body,
            "headers": {
                "ONDO-KEY-ID": self.value.api_key_id.get_secret_value(),
                "ONDO-TIMESTAMP": stamp,
                "ONDO-SIGN": signature,
                "Content-Type": "application/json",
            },
        }

    async def get(self, path: str, **params) -> dict[str, Any]:
        uri = path + ("?" + urlencode(params) if params else "")
        prepared = self.signed("GET", uri)
        return await ondo_request(self.markets, "GET", uri, headers=prepared["headers"], timeout=5)

    async def account(self, *, bind: bool = False) -> dict[str, Any]:
        data = (await self.get("/v1/account"))["result"]
        account_id = identity(data["accountID"])
        if data["accountState"] != "open" or data["disabledFunctionality"]["disablePerps"] is not False:
            raise ValueError("Ondo 账户不可交易永续合约")
        if self.value.account_id is None and bind:
            self.value.account_id = account_id
        if self.value.account_id != account_id:
            raise ValueError("Ondo API Key 的原生账户与已连接账户不匹配")
        return data

    async def validate(self) -> AccountSnapshot:
        await self.account(bind=True)
        keys = (await self.get("/v1/api_keys"))["result"]
        assert self.value.api_key_id is not None
        matches = [k for k in keys if k["keyId"] == self.value.api_key_id.get_secret_value()]
        if len(matches) != 1 or "trade" not in matches[0]["scopes"]:
            raise ValueError("Ondo API Key 未确认交易权限，请使用 View & Trade 权限")
        return await self.snapshot()

    async def snapshot(self) -> AccountSnapshot:
        await self.account()
        balance, response = await asyncio.gather(
            self.get("/v1/perps/balance"), self.get("/v1/perps/positions")
        )
        positions = []
        seen: set[str] = set()
        for row in response["result"]:
            symbol = row["market"]
            if symbol in seen:
                raise ValueError("Ondo 返回重复的原生仓位")
            seen.add(symbol)
            quantity = number(row["netQuantity"])
            direction = row["direction"]
            if (
                direction not in {"long", "short", "neutral"}
                or (direction == "neutral" and quantity != 0)
                or (direction == "long" and quantity < 0)
            ):
                raise ValueError("Ondo 仓位方向与数量不一致")
            if quantity:
                quantity = abs(quantity) * (1 if direction == "long" else -1)
                positions.append(
                    NativePosition(
                        symbol=symbol,
                        quantity=quantity,
                        entry_price=number(row["averageEntryPrice"]),
                        unrealized_pnl=number(row["unrealizedPnl"]),
                    )
                )
        data = balance["result"]
        if data["underLiquidation"] is not False:
            raise ValueError("Ondo 账户处于清算状态")
        return AccountSnapshot(
            available=number(data["availableMargin"]),
            equity=number(data["marginBalance"]),
            positions=positions,
            received_at=time.time(),
            source="Ondo 原生全仓保证金（USD 计价）",
        )

    async def margin(self, symbol: str) -> MarginSnapshot:
        await self.account()
        spec = await self.markets.spec(Provider.ONDO, symbol)
        if spec.max_leverage is None:
            raise ValueError("Ondo 杠杆上限未确认")
        rows = (await self.get("/v1/perps/leverage", market=symbol))["result"]
        if len(rows) > 1 or any(r["market"] != symbol for r in rows):
            raise ValueError("Ondo 杠杆市场身份不匹配")
        leverage = number(rows[0]["leverage"]) if rows else None
        if leverage is not None and (leverage <= 0 or leverage != leverage.to_integral_value()):
            raise ValueError("Ondo 杠杆设置无效")
        return MarginSnapshot(
            symbol=symbol,
            leverage=leverage,
            margin_mode="cross" if leverage is not None else None,
            max_leverage=spec.max_leverage,
            position_margin=None,
            received_at=time.time(),
            source="Ondo 原生全仓杠杆设置",
        )

    async def prepare_margin(self, symbol: str, capital: GridMarginCapital) -> dict[str, Any]:
        current = await self.margin(symbol)
        if capital.margin_mode != "cross" or capital.leverage > current.max_leverage:
            raise ValueError("Ondo 仅支持全仓，杠杆不能超过该市场上限")
        return self.signed(
            "POST",
            "/v1/perps/leverage",
            json.dumps({"market": symbol, "leverage": str(capital.leverage)}, separators=(",", ":")),
        )

    async def send_margin(self, prepared: dict[str, Any]) -> str | None:
        try:
            await self.submit(prepared, "/v1/perps/leverage")
        except OndoRequestError as exc:
            if exc.code not in {"invalid_leverage", "invalid_market", "insufficient_margin"}:
                raise ValueError("Ondo 杠杆设置尚未确认，需要读回核实") from None
            raise
        return None

    async def prepare(self, intent: OrderIntent) -> dict[str, Any]:
        await self.account()
        spec = await self.markets.spec(Provider.ONDO, intent.symbol)
        exact_units(intent.quantity, spec.quantity_step)
        exact_units(intent.limit_price, spec.price_tick)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", intent.client_id):
            raise ValueError("Ondo 客户端订单 ID 无效")
        body = json.dumps(
            {
                "market": spec.native_symbol,
                "side": intent.side,
                "type": "limit",
                "size": format(intent.quantity, "f"),
                "price": format(intent.limit_price, "f"),
                "clientOrderId": intent.client_id,
                "timeInForce": "IOC",
                "reduceOnly": intent.reduce_only,
                "postOnly": False,
            },
            separators=(",", ":"),
        )
        return self.signed("POST", "/v1/perps/orders", body)

    async def submit(self, prepared: dict[str, Any], path: str) -> dict[str, Any]:
        if prepared["method"] != "POST" or prepared["path"] != path:
            raise ValueError("Ondo 原提交端点不匹配")
        age = time.time() - int(prepared["headers"]["ONDO-TIMESTAMP"]) / 1000
        if not 0 <= age < 10:
            raise ValueError("Ondo 原请求签名已过期，未发送")
        return await ondo_request(
            self.markets,
            "POST",
            path,
            headers=prepared["headers"],
            content=prepared["body"],
            follow_redirects=False,
        )

    async def send(self, prepared: dict[str, Any]) -> str | None:
        try:
            data = await self.submit(prepared, "/v1/perps/orders")
        except OndoRequestError as exc:
            if exc.status_code == 400 and exc.code in ORDER_REJECTIONS:
                raise OrderRejected("Ondo 明确拒绝原订单") from None
            raise
        return identity(data["result"]["orderId"])

    async def open_orders(self, symbol: str) -> list[dict[str, Any]]:
        await self.account()
        result, cursor, cursors = [], None, set()
        for _ in range(20):
            params: dict[str, Any] = {"market": symbol, "status": "open", "limit": 1000}
            if cursor is not None:
                params["cursor"] = cursor
            response = await self.get("/v1/perps/orders", **params)
            rows = response["result"]
            if any(row["market"] != symbol for row in rows):
                raise ValueError("Ondo 挂单市场身份不符")
            result.extend(rows)
            page = response.get("pageInfo")
            if page is not None and not isinstance(page, dict):
                raise ValueError("Ondo 挂单分页元数据无效")
            cursor = page.get("nextCursor") if page is not None else None
            if page is None and len(rows) >= 1000:
                raise ValueError("Ondo 挂单满页但缺少分页信息，读取不完整")
            if cursor is None:
                twaps = (await self.get("/v1/perps/twap/orders/running", market=symbol))["result"]
                if any(row["market"] != symbol for row in twaps):
                    raise ValueError("Ondo TWAP 市场身份不符")
                return result + twaps
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("Ondo 挂单分页身份无效")
            cursors.add(cursor)
        raise ValueError("Ondo 挂单读取不完整")

    async def lookup(self, intent: OrderIntent, native_id: str | None) -> OrderResult:
        await self.account()
        original = quote("client:" + intent.client_id, safe="")
        try:
            row = (await self.get("/v1/perps/orders/" + original))["result"]
        except OndoRequestError as exc:
            if exc.status_code == 400 and exc.code == "order_not_found":
                return self.unknown(native_id)
            raise
        oid = identity(row["orderId"])
        if (
            row["clientOrderId"] != intent.client_id
            or row["market"] != intent.symbol
            or row["side"] != intent.side
            or row["type"] != "limit"
            or row["timeInForce"] != "IOC"
            or row["reduceOnly"] is not intent.reduce_only
            or number(row["size"]) != intent.quantity
            or number(row["price"]) != intent.limit_price
            or (native_id is not None and oid != native_id)
        ):
            raise ValueError("Ondo 原订单身份与本地提交不符")
        if row["status"] not in {"fullyfilled", "canceled"}:
            return self.unknown(oid)
        quantity, cost = number(row["filledSize"]), number(row["filledCost"])
        if not 0 <= quantity <= intent.quantity or (
            row["status"] == "fullyfilled" and quantity != intent.quantity
        ):
            raise ValueError("Ondo 原订单累计数量无效")
        fills = (await self.get(f"/v1/perps/orders/{quote(oid, safe='')}/fills"))["result"]
        total, notional, fees, rebates, ids = Decimal(0), Decimal(0), Decimal(0), [], set()
        for fill in fills:
            fid = identity(fill["id"])
            if (
                fid in ids
                or fill["orderId"] != oid
                or fill["clientOrderId"] != intent.client_id
                or fill["market"] != intent.symbol
                or fill["side"] != intent.side
            ):
                raise ValueError("Ondo 原始成交身份无效或重复")
            ids.add(fid)
            size, price, filled_cost = number(fill["size"]), number(fill["price"]), number(fill["filledCost"])
            if (
                size <= 0
                or price <= 0
                or filled_cost != size * price
                or (intent.side == "buy" and price > intent.limit_price)
                or (intent.side == "sell" and price < intent.limit_price)
            ):
                raise ValueError("Ondo 成交数量或价格无效")
            total += size
            notional += filled_cost
            gross = number(fill["fee"])
            rebate = number(fill["feeRebate"]) if "feeRebate" in fill else None
            if gross < 0 or (rebate is not None and rebate < 0):
                raise ValueError("Ondo 原生费用或返佣数据无效")
            fees += gross
            rebates.append(rebate)
        if total != quantity or notional != cost or fees != number(row["fee"]):
            return self.unknown(oid)
        fee = (
            fees - sum((r for r in rebates if r is not None), Decimal(0))
            if all(r is not None for r in rebates)
            else None
        )
        return OrderResult(
            status="filled" if row["status"] == "fullyfilled" else "canceled",
            quantity=quantity,
            average_price=cost / quantity if quantity else None,
            fee=fee,
            native_id=oid,
        )
