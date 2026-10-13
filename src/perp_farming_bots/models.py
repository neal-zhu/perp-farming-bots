from __future__ import annotations

import time
from decimal import Decimal
from enum import StrEnum
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class Provider(StrEnum):
    LIGHTER = "lighter"
    LIGHTER_RH = "lighter_robinhood"
    ARCUS = "arcus"
    HYPERLIQUID = "hyperliquid"
    BINANCE = "binance"


PROVIDER_NAMES = {
    Provider.LIGHTER: "Lighter Core",
    Provider.LIGHTER_RH: "Lighter Robinhood",
    Provider.ARCUS: "Arcus",
    Provider.HYPERLIQUID: "Hyperliquid",
    Provider.BINANCE: "Binance USD-M",
}
TRADING_PROVIDERS = {Provider.ARCUS, Provider.LIGHTER, Provider.LIGHTER_RH}
SUPPORTED_ASSETS = {"BTC", "ETH", "SOL"}


class BotState(StrEnum):
    READY = "ready"
    WAITING = "waiting"
    HOLDING = "holding"
    PAUSED = "paused"
    CLOSED = "closed"
    ATTENTION = "attention"


STATE_NAMES = {
    BotState.READY: "待运行",
    BotState.WAITING: "等待价差",
    BotState.HOLDING: "持仓中",
    BotState.PAUSED: "已暂停",
    BotState.CLOSED: "已平仓",
    BotState.ATTENTION: "需要处理",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectionCreate(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    provider: Provider
    account_index: int = Field(ge=0, lt=2**48)
    address: str | None = Field(default=None, pattern=r"^0x[0-9a-fA-F]{40}$")
    api_key_index: int | None = Field(default=None, ge=0, le=254)
    api_private_key: SecretStr = Field(min_length=32, max_length=256)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()

    @model_validator(mode="after")
    def valid_credentials(self) -> ConnectionCreate:
        if self.provider not in TRADING_PROVIDERS:
            raise ValueError("该交易所的账户接入尚未完成")
        if self.provider == Provider.ARCUS:
            if self.address is None or self.account_index > 9 or self.api_key_index is not None:
                raise ValueError("Arcus 需要钱包地址和 0–9 的子账户编号，不使用 API key 编号")
            try:
                key = bytes.fromhex(self.api_private_key.get_secret_value().removeprefix("0x"))
            except ValueError as exc:
                raise ValueError("Arcus API Signing Key 必须是十六进制") from exc
            if len(key) != 32:
                raise ValueError("Arcus API Signing Key 必须是 32 字节")
        elif self.api_key_index is None:
            raise ValueError("Lighter 需要 API key 编号")
        if self.address is not None:
            self.address = self.address.lower()
        return self


class Connection(StrictModel):
    id: str
    name: str
    provider: Provider
    account_index: int
    address: str | None
    api_key_index: int | None
    account_ref: str
    created_at: float
    verified_at: float


class HedgeParameters(StrictModel):
    long_connection_id: str
    short_connection_id: str
    symbol: str = Field(min_length=1, max_length=30, pattern=r"^[A-Z0-9]+$")
    threshold_pct: Decimal = Field(ge=Decimal("-10"), le=Decimal("100"))
    target_usd: Decimal = Field(gt=0, le=Decimal("1000000"))
    slippage_bps: Decimal = Field(default=Decimal("20"), ge=0, le=Decimal("100"))
    reopen_interval_seconds: int | None = Field(default=None, ge=60, le=2592000)
    reopen_random_wait_seconds: int = Field(default=300, ge=0, le=300)

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def valid_pair(self) -> HedgeParameters:
        if self.long_connection_id == self.short_connection_id:
            raise ValueError("两条腿必须绑定不同账户实例；可以属于同一交易所")
        if self.symbol not in SUPPORTED_ASSETS:
            raise ValueError("首批支持 BTC、ETH、SOL 标准加密资产永续；其他合约等待单位核实")
        return self


class BotUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    parameters: HedgeParameters

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Bot 名称不能为空")
        return value.strip()


class BotCreate(BotUpdate):
    request_id: str = Field(min_length=8, max_length=80)
    strategy: str = "spread_hedging"

    @field_validator("strategy")
    @classmethod
    def implemented_strategy(cls, value: str) -> str:
        if value != "spread_hedging":
            raise ValueError("网格和剥头皮尚未实现")
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

    def limit_price(self, side: str, quantity: Decimal) -> Decimal:
        remaining = quantity
        for level in self.asks if side == "buy" else self.bids:
            remaining -= min(level.quantity, remaining)
            if remaining == 0:
                return level.price
        raise ValueError("所需数量超出当前盘口深度")


class MarketSpec(StrictModel):
    provider: Provider
    symbol: str
    native_symbol: str
    market_id: int
    quantity_step: Decimal = Field(gt=0)
    price_tick: Decimal = Field(gt=0)
    min_quantity: Decimal = Field(ge=0)
    min_notional: Decimal = Field(ge=0)
    tick_tiers: list[dict[str, str]] = Field(default_factory=list)


class Preview(StrictModel):
    quantity: Decimal
    long_price: Decimal
    short_price: Decimal
    spread_pct: Decimal
    estimated_fees: Decimal | None
    source: str


class FundingSnapshot(StrictModel):
    provider: Provider
    symbol: str
    status: Literal["available", "unavailable"]
    # Percent per native settlement interval, not an annualized or 8-hour rate.
    predicted_rate_pct: Decimal | None = Field(allow_inf_nan=False)
    last_rate_pct: Decimal | None = Field(allow_inf_nan=False)
    interval_seconds: int = Field(gt=0)
    next_payment_at: float | None
    received_at: float | None
    source: str
    unavailable_reason: str | None

    @model_validator(mode="after")
    def valid_state(self) -> FundingSnapshot:
        values = [self.predicted_rate_pct, self.last_rate_pct, self.next_payment_at, self.received_at]
        if self.status == "available" and (
            any(v is None for v in values) or self.unavailable_reason is not None
        ):
            raise ValueError("可用的资金费率必须包含完整数据")
        if self.status == "unavailable" and (
            any(v is not None for v in values) or not self.unavailable_reason
        ):
            raise ValueError("不可用的资金费率必须明确原因，不能包含未经确认的数据")
        return self


class Position(StrictModel):
    bot_id: str
    connection_id: str
    role: str
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    opening_fee: Decimal | None


class NativePosition(StrictModel):
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    unrealized_pnl: Decimal | None


class AccountSnapshot(StrictModel):
    available: Decimal
    equity: Decimal
    positions: list[NativePosition]
    received_at: float
    source: str


class OrderIntent(StrictModel):
    connection_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0)
    limit_price: Decimal = Field(gt=0)
    reduce_only: bool
    client_id: str


class OrderResult(StrictModel):
    status: str
    quantity: Decimal | None
    average_price: Decimal | None
    fee: Decimal | None
    native_id: str | None

    @model_validator(mode="after")
    def evidence(self) -> OrderResult:
        if self.status not in {"filled", "canceled", "rejected", "unknown"}:
            raise ValueError("未知订单状态")
        if self.status != "unknown":
            if self.quantity is None or self.quantity < 0 or not self.quantity.is_finite():
                raise ValueError("终态订单缺少有效成交数量")
            if self.quantity > 0 and (self.average_price is None or self.average_price <= 0):
                raise ValueError("已成交订单缺少成交价格")
        return self


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
        "description": "两个账户、一个币种，价差达到条件后建仓；可设置持仓间隔，定期平仓后再次等待价差。",
    },
    {
        "id": "grid",
        "name": "永续网格",
        "available": False,
        "description": "价格区间、网格数量和预算。开发中。",
    },
    {
        "id": "scalping",
        "name": "剥头皮",
        "available": False,
        "description": "明确的短线入场和出场规则。开发中。",
    },
]
