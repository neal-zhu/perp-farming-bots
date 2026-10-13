"""Native units: Arcus decimal fractions; Lighter rules in 1e-4, account IMF in percent."""

import time
from decimal import Decimal
from typing import Literal

from .markets import Markets
from .models import ConnectionCreate, MarginSnapshot, Provider


async def read_native_margin(value: ConnectionCreate, markets: Markets, symbol: str) -> MarginSnapshot:
    mode: Literal["cross", "isolated"] | None
    leverage: Decimal | None
    position_margin: Decimal | None
    spec = await markets.spec(value.provider, symbol)
    if value.provider == Provider.ARCUS:
        rules = await markets.request(value.provider, "GET", "/v1/markets")
        rows = [r for r in rules["markets"] if r["marketId"] == spec.market_id and r["baseAsset"] == symbol]
        if len(rows) != 1:
            raise ValueError("保证金规则市场身份不匹配")
        fraction = Decimal(rows[0]["initialMarginFraction"])
        r = await markets.request(
            value.provider,
            "GET",
            "/v1/leverages",
            params={"address": value.address, "accountIndex": value.account_index},
        )
        if r["address"].lower() != value.address or r["accountIndex"] != value.account_index:
            raise ValueError("杠杆账户身份不匹配")
        entries = [
            e
            for e in r["leverages"]
            if e["marketId"] == spec.market_id and e["marketDisplayName"] == spec.native_symbol
        ]
        if len(entries) != 1:
            raise ValueError("原生杠杆记录缺失或市场身份不匹配")
        e = entries[0]
        if type(e["isolated"]) is not bool or e["marginMode"] != ("ISOLATED" if e["isolated"] else "CROSS"):
            raise ValueError("保证金模式记录不一致")
        if type(e["leverage"]) is not int or e["leverage"] < 1:
            raise ValueError("原生杠杆值无效")
        leverage, mode = Decimal(e["leverage"]), "isolated" if e["isolated"] else "cross"
        position_margin = None
        if mode == "isolated":
            account = await markets.request(
                value.provider,
                "GET",
                "/v1/account",
                params={"address": value.address, "accountIndex": value.account_index},
            )
            if account["address"].lower() != value.address or account["accountIndex"] != value.account_index:
                raise ValueError("逐仓保证金账户身份不匹配")
            positions = [
                p
                for p in account["positions"].values()
                if p["marketDisplayName"] == spec.native_symbol and Decimal(p["size"]) != 0
            ]
            if len(positions) > 1:
                raise ValueError("逐仓保证金出现多个原生仓位")
            position_margin = Decimal(positions[0]["marginUsed"]) if positions else Decimal(0)
    else:
        rules = await markets.request(value.provider, "GET", "/api/v1/orderBookDetails")
        rows = [
            r
            for r in rules["order_book_details"]
            if r["market_id"] == spec.market_id and r["symbol"] == symbol
        ]
        if len(rows) != 1:
            raise ValueError("保证金规则市场身份不匹配")
        fraction = Decimal(rows[0]["min_initial_margin_fraction"]) / 10000
        r = await markets.request(
            value.provider,
            "GET",
            "/api/v1/account",
            params={"by": "index", "value": str(value.account_index)},
        )
        accounts = [a for a in r["accounts"] if a["account_index"] == value.account_index]
        if (
            len(accounts) != 1
            or value.address is not None
            and accounts[0]["l1_address"].lower() != value.address
        ):
            raise ValueError("杠杆账户身份不匹配")
        entries = [
            e for e in accounts[0]["positions"] if e["market_id"] == spec.market_id and e["symbol"] == symbol
        ]
        leverage, mode, position_margin = None, None, None
        if len(entries) > 1:
            raise ValueError("原生杠杆记录重复")
        if entries:
            e = entries[0]
            imf = Decimal(e["initial_margin_fraction"]) / 100
            if (
                not imf.is_finite()
                or not 0 < imf <= 1
                or type(e["margin_mode"]) is not int
                or e["margin_mode"] not in {0, 1}
            ):
                raise ValueError("原生保证金比例或模式无效")
            leverage, mode = 1 / imf, "cross" if e["margin_mode"] == 0 else "isolated"
            if mode == "isolated":
                position_margin = Decimal(e["allocated_margin"])
    if not fraction.is_finite() or not 0 < fraction <= 1:
        raise ValueError("原生市场保证金比例无效")
    return MarginSnapshot(
        symbol=symbol,
        leverage=leverage,
        margin_mode=mode,
        max_leverage=1 / fraction,
        position_margin=position_margin,
        received_at=time.time(),
        source=f"{value.provider.value} 原生保证金设置",
    )
