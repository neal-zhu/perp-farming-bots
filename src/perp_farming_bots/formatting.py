import os
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


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
