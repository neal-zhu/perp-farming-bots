"""Entropy's standard crypto markets settle on Hyperliquid's main perpetual DEX.

Only official SDK signing is reused. HTTP transport stays in the shared journaled
executor. Entropy's own HIP-3 instruments are separate markets and are not aliases.
"""

from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Any

from eth_account import Account
from hyperliquid.utils.signing import sign_l1_action

from .markets import Markets
from .models import (
    SUPPORTED_ASSETS,
    AccountSnapshot,
    GridMarginCapital,
    MarginSnapshot,
    MarketSpec,
    NativePosition,
    OrderIntent,
    OrderResult,
    Provider,
)
from .trading import Adapter

# Verified from entropy.io's publicly served builder configuration, 2026-10-14.
# Zero added builder fee. Do not silently raise this if the website changes.
ENTROPY_BUILDER = "0xcd254d2a328f7f67c7c6fef930a4757516f7b601"
ENTROPY_BUILDER_FEE = 0
ALLOWED_ACCOUNT_MODES = {"default", "disabled", "dexAbstraction"}
CANCELED = {
    "canceled",
    "marginCanceled",
    "vaultWithdrawalCanceled",
    "openInterestCapCanceled",
    "selfTradeCanceled",
    "reduceOnlyCanceled",
    "siblingFilledCanceled",
    "delistedCanceled",
    "liquidatedCanceled",
    "scheduledCancel",
}
REJECTED = {
    "rejected",
    "tickRejected",
    "minTradeNtlRejected",
    "perpMarginRejected",
    "reduceOnlyRejected",
    "badAloPxRejected",
    "iocCancelRejected",
    "badTriggerPxRejected",
    "marketOrderNoLiquidityRejected",
    "positionIncreaseAtOpenInterestCapRejected",
    "positionFlipAtOpenInterestCapRejected",
    "tooAggressiveAtOpenInterestCapRejected",
    "openInterestIncreaseRejected",
    "insufficientSpotBalanceRejected",
    "oracleRejected",
    "perpMaxPositionRejected",
}


def number(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("Entropy 原生金额缺失或无效")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Entropy 原生金额无效")
    return result


async def market_rules(markets: Markets, spec: MarketSpec) -> dict[str, Any]:
    meta = await markets.entropy_info("meta", dex="")
    if not 0 <= spec.market_id < len(meta["universe"]):
        raise ValueError("Entropy 原生合约编号无效")
    row = meta["universe"][spec.market_id]
    if row["name"] != spec.native_symbol or row.get("isDelisted") is True:
        raise ValueError("Entropy 原生市场身份或状态不符")
    return row


async def entropy_catalog(markets: Markets) -> dict[str, MarketSpec]:
    meta = await markets.entropy_info("meta", dex="")
    catalog = {}
    for index, row in enumerate(meta["universe"]):
        symbol = row["name"]
        if symbol not in SUPPORTED_ASSETS or row.get("isDelisted") is True:
            continue
        size_decimals = row["szDecimals"]
        if type(size_decimals) is not int or not 0 <= size_decimals <= 6:
            raise ValueError("Entropy 合约数量精度无效")
        decimals = 6 - size_decimals
        catalog[symbol] = MarketSpec(
            provider=Provider.ENTROPY,
            symbol=symbol,
            native_symbol=symbol,
            market_id=index,
            quantity_step=Decimal(10) ** -size_decimals,
            min_quantity=Decimal(10) ** -size_decimals,
            min_notional=Decimal("10"),
            price_tick=Decimal(1),
            # 5 significant digits for fractional prices; integer prices are valid.
            tick_tiers=[
                {"upToPrice": str(Decimal(10) ** (exponent + 5)), "tick": str(Decimal(10) ** exponent)}
                for exponent in range(-decimals, 0)
            ],
        )
    return catalog


async def entropy_funding(markets: Markets, spec: MarketSpec) -> dict[str, Any]:
    meta, contexts = await markets.entropy_info("metaAndAssetCtxs", dex="")
    if meta["universe"][spec.market_id]["name"] != spec.native_symbol:
        raise ValueError("Entropy 资金费率市场身份不符")
    now = time.time()
    history = await markets.entropy_info(
        "fundingHistory", coin=spec.native_symbol, startTime=int((now - 7200) * 1000)
    )
    if not history:
        raise ValueError("Entropy 上次结算资金费率尚未返回")
    last = max(history, key=lambda item: item["time"])
    if last["coin"] != spec.native_symbol or not 0 <= now - last["time"] / 1000 <= 7200:
        raise ValueError("Entropy 历史资金费率身份或时间无效")
    return {
        "predicted_rate_pct": number(contexts[spec.market_id]["funding"]) * 100,
        "last_rate_pct": number(last["fundingRate"]) * 100,
        "next_payment_at": (int(now) // 3600 + 1) * 3600,
    }


class Entropy(Adapter):
    def __init__(self, value, markets: Markets):
        super().__init__(value, markets)
        self.key = Account.from_key(value.api_private_key.get_secret_value())
        self.last_nonce = 0
        self.rejections: dict[str, OrderResult] = {}

    async def validate(self) -> AccountSnapshot:
        role = await self.markets.entropy_info("userRole", user=self.value.address)
        if role["role"] != "user":
            raise ValueError("Entropy 请填写主交易账户地址；代理地址、子账户和 Vault 暂不支持")
        key_role = await self.markets.entropy_info("userRole", user=self.key.address)
        if key_role["role"] != "agent" or key_role["data"]["user"].lower() != self.value.address:
            raise ValueError("Entropy API 代理密钥未授权给该交易账户；请在 Hyperliquid API 页面创建代理")
        agents = await self.markets.entropy_info("extraAgents", user=self.value.address)
        matching = [a for a in agents if a["address"].lower() == self.key.address.lower()]
        if len(matching) != 1 or matching[0]["validUntil"] <= time.time() * 1000:
            raise ValueError("Entropy API 代理授权不存在或已过期")
        await self.check_builder()
        return await self.snapshot()

    async def check_builder(self):
        approved = await self.markets.entropy_info("approvedBuilders", user=self.value.address)
        if ENTROPY_BUILDER not in [address.lower() for address in approved]:
            raise ValueError("请先在 Entropy 官网连接此账户并完成交易授权，再连接 Bot")

    async def snapshot(self) -> AccountSnapshot:
        mode = await self.markets.entropy_info("userAbstraction", user=self.value.address)
        if mode not in ALLOWED_ACCOUNT_MODES:
            raise ValueError("Entropy 统一账户或组合保证金模式暂未支持，无法确认可用保证金")
        data = await self.markets.entropy_info("clearinghouseState", user=self.value.address, dex="")
        received_at = data["time"] / 1000
        if not 0 <= time.time() - received_at <= 30:
            raise ValueError("Entropy 账户快照时间无效或已过期")
        positions = []
        for entry in data["assetPositions"]:
            p = entry["position"]
            quantity = number(p["szi"])
            if quantity:
                positions.append(
                    NativePosition(
                        symbol=p["coin"],
                        quantity=quantity,
                        entry_price=number(p["entryPx"]),
                        unrealized_pnl=number(p["unrealizedPnl"]),
                    )
                )
        return AccountSnapshot(
            available=number(data["withdrawable"]),
            equity=number(data["marginSummary"]["accountValue"]),
            positions=positions,
            received_at=received_at,
            source="Entropy / Hyperliquid 原生账户",
        )

    def signed(self, action: dict[str, Any]) -> dict[str, Any]:
        nonce = max(int(time.time() * 1000), self.last_nonce + 1)
        self.last_nonce = nonce
        expires = nonce + 30_000
        return {
            "action": action,
            "nonce": nonce,
            "signature": sign_l1_action(self.key, action, None, nonce, expires, True),
            "vaultAddress": None,
            "expiresAfter": expires,
        }

    async def prepare(self, intent: OrderIntent) -> dict[str, Any]:
        spec = await self.markets.spec(Provider.ENTROPY, intent.symbol)
        if not re.fullmatch(r"[0-9a-f]{32}", intent.client_id):
            raise ValueError("Entropy 客户端订单编号必须是 128 位十六进制")
        await self.check_builder()
        return self.signed(
            {
                "type": "order",
                "orders": [
                    {
                        "a": spec.market_id,
                        "b": intent.side == "buy",
                        "p": format(intent.limit_price, "f"),
                        "s": format(intent.quantity, "f"),
                        "r": intent.reduce_only,
                        "t": {"limit": {"tif": "Ioc"}},
                        "c": "0x" + intent.client_id,
                    }
                ],
                "grouping": "na",
                "builder": {"b": ENTROPY_BUILDER, "f": ENTROPY_BUILDER_FEE},
            }
        )

    async def send(self, prepared: dict[str, Any]) -> str | None:
        data = await self.markets.request(Provider.ENTROPY, "POST", "/exchange", json=prepared)
        if data["status"] != "ok":
            raise ValueError("Entropy 原生订单返回错误，请查询原订单")
        statuses = data["response"]["data"]["statuses"]
        if len(statuses) != 1:
            raise ValueError("Entropy 返回的订单数量不符")
        result = statuses[0]
        if "error" in result:
            # Native explicit rejection is evidence. Lost responses never enter this cache.
            cloid = prepared["action"]["orders"][0]["c"]
            self.rejections[cloid] = OrderResult(
                status="rejected", quantity=Decimal(0), average_price=None, fee=Decimal(0), native_id=None
            )
            return None
        if "filled" in result:
            return str(result["filled"]["oid"])
        if "resting" in result:
            return str(result["resting"]["oid"])
        raise ValueError("Entropy 原生订单回报不完整")

    async def lookup(self, intent: OrderIntent, native_id: str | None) -> OrderResult:
        cloid = "0x" + intent.client_id
        if cloid in self.rejections:
            return self.rejections[cloid]
        data = await self.markets.entropy_info(
            "orderStatus", user=self.value.address, oid=int(native_id) if native_id else cloid
        )
        if data["status"] != "order":
            return self.unknown(native_id)
        row, status = data["order"]["order"], data["order"]["status"]
        oid = str(row["oid"])
        if (
            row["coin"] != intent.symbol
            or row["cloid"] != cloid
            or row["side"] != ("B" if intent.side == "buy" else "A")
            or number(row["origSz"]) != intent.quantity
            or number(row["limitPx"]) != intent.limit_price
            or row["reduceOnly"] is not intent.reduce_only
            or native_id is not None
            and oid != native_id
        ):
            raise ValueError("Entropy 原订单身份不符")
        if status != "filled" and status not in CANCELED | REJECTED:
            return self.unknown(oid)
        native_fills = await self.markets.entropy_info(
            "userFillsByTime",
            user=self.value.address,
            startTime=row["timestamp"],
            endTime=int(time.time() * 1000),
            aggregateByTime=False,
        )
        if len(native_fills) >= 2000:
            return self.unknown(oid)  # A truncated history cannot prove the complete fill.
        quantity, cost = Decimal(0), Decimal(0)
        fee: Decimal | None = Decimal(0)
        tids = set()
        for fill in native_fills:
            if str(fill["oid"]) != oid:
                continue
            if fill["coin"] != intent.symbol or fill["side"] != row["side"] or fill["tid"] in tids:
                raise ValueError("Entropy 成交身份不符或重复")
            tids.add(fill["tid"])
            size, price = number(fill["sz"]), number(fill["px"])
            if size <= 0 or price <= 0:
                raise ValueError("Entropy 成交数量或价格无效")
            quantity += size
            cost += size * price
            fee = None if fee is None or fill["feeToken"] != "USDC" else fee + number(fill["fee"])
        if quantity > intent.quantity or status == "filled" and quantity != intent.quantity:
            return self.unknown(oid)
        if status in CANCELED and quantity != intent.quantity - number(row["sz"]):
            return self.unknown(oid)
        if status in REJECTED and quantity:
            return self.unknown(oid)
        return OrderResult(
            status="filled" if status == "filled" else "canceled" if status in CANCELED else "rejected",
            quantity=quantity,
            average_price=cost / quantity if quantity else None,
            fee=fee,
            native_id=oid,
        )

    async def open_orders(self, symbol: str) -> list[dict[str, Any]]:
        rows = await self.markets.entropy_info("openOrders", user=self.value.address, dex="")
        return [order for order in rows if order["coin"] == symbol]

    async def margin(self, symbol: str) -> MarginSnapshot:
        spec = await self.markets.spec(Provider.ENTROPY, symbol)
        rules = await market_rules(self.markets, spec)
        data = await self.markets.entropy_info("activeAssetData", user=self.value.address, coin=symbol)
        if data["user"].lower() != self.value.address or data["coin"] != symbol:
            raise ValueError("Entropy 保证金账户或市场身份不符")
        settings = data["leverage"]
        if settings["type"] not in {"cross", "isolated"}:
            raise ValueError("Entropy 原生保证金模式无效")
        return MarginSnapshot(
            symbol=symbol,
            leverage=number(settings["value"]),
            margin_mode=settings["type"],
            max_leverage=number(rules["maxLeverage"]),
            position_margin=None,
            received_at=time.time(),
            source="Entropy / Hyperliquid 原生保证金设置",
        )

    async def prepare_margin(self, symbol: str, capital: GridMarginCapital) -> dict[str, Any]:
        spec = await self.markets.spec(Provider.ENTROPY, symbol)
        rules = await market_rules(self.markets, spec)
        if (
            capital.leverage > rules["maxLeverage"]
            or capital.margin_mode == "cross"
            and (
                rules.get("onlyIsolated") is True or rules.get("marginMode") in {"noCross", "strictIsolated"}
            )
        ):
            raise ValueError("Entropy 杠杆或保证金模式超出原生市场规则")
        return self.signed(
            {
                "type": "updateLeverage",
                "asset": spec.market_id,
                "isCross": capital.margin_mode == "cross",
                "leverage": capital.leverage,
            }
        )

    async def send_margin(self, prepared: dict[str, Any]) -> str | None:
        data = await self.markets.request(Provider.ENTROPY, "POST", "/exchange", json=prepared)
        if data["status"] != "ok":
            raise ValueError("Entropy 保证金设置未确认，请同步原设置")
        return None  # The shared margin journal confirms by reading activeAssetData.
