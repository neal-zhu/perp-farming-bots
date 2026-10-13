"""Small, isolated adaptation of Hummingbot's public grid geometry utility.

Source: hummingbot/strategy_v2/utils/distributions.py, Distributions.linear
Commit: 9af100d6822da7d2d0291a906c730ef172284ee2 (Apache-2.0).
Changes: Decimal-only inputs and explicit invalid-input rejection. No float conversion.
See third_party/hummingbot/LICENSE and NOTICE for redistribution attribution.
"""

from decimal import Decimal


def linear(n_levels: int, start: Decimal, end: Decimal) -> list[Decimal]:
    if n_levels < 2 or not start.is_finite() or not end.is_finite() or start <= 0 or end <= start:
        raise ValueError("网格需要至少两条有效、递增的格线")
    return [start + (end - start) * Decimal(i) / (Decimal(n_levels) - 1) for i in range(n_levels)]
