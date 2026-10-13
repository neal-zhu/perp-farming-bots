import os
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from .models import GridParameters


def grid_capital_text(p: GridParameters) -> str:
    return f"保证金额度 {money(p.capital.investment_usd)} · {p.capital.leverage} 倍 · {'全仓' if p.capital.margin_mode == 'cross' else '逐仓'} · Bot 持仓上限（区间内） {money(p.notional_limit)}"


def money(value: str | Decimal | None) -> str:
    if value is None:
        return "待确认"
    rounded = Decimal(value).quantize(Decimal("0.01"))
    return f"${abs(rounded) if rounded == 0 else rounded:,.2f}"


def pnl_money(value: str | Decimal | None) -> str:
    if value is None:
        return "待确认"
    rounded = Decimal(value).quantize(Decimal("0.01"))
    if rounded == 0:
        return "$0.00"
    return ("+" if rounded > 0 else "−") + money(abs(rounded))


def rate(value: str | Decimal) -> str:
    return format(Decimal(value).normalize(), "f") + "%"


def stamp(value: float) -> str:
    return datetime.fromtimestamp(value, ZoneInfo(os.environ.get("PFB_TIMEZONE", "Asia/Shanghai"))).strftime(
        "%m-%d %H:%M:%S"
    )
