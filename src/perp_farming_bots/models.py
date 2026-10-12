from __future__ import annotations

import time
from decimal import Decimal
from enum import StrEnum
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Provider(StrEnum):
    DEMO_A = "demo_a"
    DEMO_B = "demo_b"
    LIGHTER = "lighter"
    LIGHTER_RH = "lighter_robinhood"
    HYPERLIQUID = "hyperliquid"
    BINANCE = "binance"
    ARCUS = "arcus"


PROVIDER_NAMES = {
    Provider.DEMO_A: "演示市场 A（虚构行情）",
    Provider.DEMO_B: "演示市场 B（虚构行情）",
    Provider.LIGHTER: "Lighter Core",
    Provider.LIGHTER_RH: "Lighter Robinhood",
    Provider.HYPERLIQUID: "Hyperliquid",
    Provider.BINANCE: "Binance USD-M",
    Provider.ARCUS: "Arcus（接入开发中）",
}


class BotState(StrEnum):
    READY = "ready"
    WAITING = "waiting"
    HOLDING = "holding"
    PAUSED = "paused"
    STOPPED = "stopped"
    CLOSED = "closed"
    ATTENTION = "attention"


STATE_NAMES = {
    BotState.READY: "待启动",
    BotState.WAITING: "等待价差",
    BotState.HOLDING: "持仓中",
    BotState.PAUSED: "已暂停",
    BotState.STOPPED: "已停止（可能仍持仓）",
    BotState.CLOSED: "已平仓",
    BotState.ATTENTION: "需要处理",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectionCreate(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    provider: Provider
    account_ref: str = Field(min_length=1, max_length=120)
    paper_balance: Decimal = Field(default=Decimal("10000"), gt=0, le=Decimal("100000000"))
    paper_fee_bps: Decimal = Field(default=Decimal("2"), ge=0, le=Decimal("100"))

    @field_validator("name", "account_ref")
    @classmethod
    def clean_string(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称和账户身份不能为空")
        return value

    @field_validator("paper_balance", "paper_fee_bps")
    @classmethod
    def finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("金额必须是有限数字")
        return value


class Connection(ConnectionCreate):
    id: str
    created_at: float


class HedgeParameters(StrictModel):
    long_connection_id: str
    short_connection_id: str
    symbol: str = Field(min_length=1, max_length=30, pattern=r"^[A-Z0-9]+$")
    threshold_pct: Decimal = Field(ge=Decimal("-10"), le=Decimal("100"))
    target_usd: Decimal = Field(gt=0, le=Decimal("1000000"))

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def distinct_accounts(self) -> HedgeParameters:
        if self.long_connection_id == self.short_connection_id:
            raise ValueError("两条腿必须绑定不同账户实例；可以属于同一交易所")
        return self


class BotCreate(StrictModel):
    request_id: str = Field(min_length=8, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    strategy: str = "spread_hedging"
    parameters: HedgeParameters

    @field_validator("strategy")
    @classmethod
    def implemented_strategy(cls, value: str) -> str:
        if value != "spread_hedging":
            raise ValueError("网格和剥头皮尚未实现，当前可运行跨账户价差对冲")
        return value

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Bot 名称不能为空")
        return value


class Bot(BotCreate):
    id: str
    state: BotState
    reason: str
    created_at: float
    updated_at: float


class Level(StrictModel):
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)


class Book(StrictModel):
    provider: Provider
    symbol: str
    bids: list[Level]
    asks: list[Level]
    received_at: float
    source: str

    @model_validator(mode="after")
    def validate_book(self) -> Book:
        if not self.bids or not self.asks:
            raise ValueError("盘口为空")
        if self.bids[0].price >= self.asks[0].price:
            raise ValueError("盘口价格交叉")
        for level in self.bids + self.asks:
            if not level.price.is_finite() or not level.quantity.is_finite():
                raise ValueError("盘口价格或数量无效")
        return self

    def fresh(self, max_age: float = 15) -> bool:
        return 0 <= time.time() - self.received_at <= max_age

    def vwap(self, side: str, quantity: Decimal) -> Decimal:
        if side not in {"buy", "sell"} or quantity <= 0:
            raise ValueError("报价方向或数量无效")
        remaining, cost = quantity, Decimal(0)
        for level in self.asks if side == "buy" else self.bids:
            take = min(level.quantity, remaining)
            cost += take * level.price
            remaining -= take
            if remaining == 0:
                return cost / quantity
        raise ValueError("所需数量超出当前盘口深度")


class Preview(StrictModel):
    quantity: Decimal
    long_price: Decimal
    short_price: Decimal
    spread_pct: Decimal
    estimated_fees: Decimal
    source: str


class Position(StrictModel):
    bot_id: str
    connection_id: str
    role: str
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    opening_fee: Decimal


class StrategyDefinition(TypedDict):
    id: str
    name: str
    available: bool
    description: str


STRATEGIES: list[StrategyDefinition] = [
    {
        "id": "spread_hedging",
        "name": "跨账户价差对冲",
        "available": True,
        "description": "两个账户、一个币种，价差达到条件后模拟建仓；支持同一交易所的不同账户。",
    },
    {
        "id": "grid",
        "name": "永续网格",
        "available": False,
        "description": "价格区间、网格数量和预算。规则定义后再开放。",
    },
    {
        "id": "scalping",
        "name": "剥头皮",
        "available": False,
        "description": "明确的短线入场和出场规则。当前未实现。",
    },
]
