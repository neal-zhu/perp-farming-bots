import os
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


def money(value: str | Decimal | None) -> str:
    return "待确认" if value is None else f"${Decimal(value):,.2f}"


def stamp(value: float) -> str:
    return datetime.fromtimestamp(value, ZoneInfo(os.environ.get("PFB_TIMEZONE", "Asia/Shanghai"))).strftime(
        "%m-%d %H:%M:%S"
    )
