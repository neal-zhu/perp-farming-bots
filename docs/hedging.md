# Cross-account spread hedging

Strategy ID: `spread_hedging`. Implementation: [runtime.py](../src/perp_farming_bots/runtime.py). Parameters: `HedgeParameters` in [models.py](../src/perp_farming_bots/models.py).

## Entry

Bind two different account instances, a supported symbol, long/short direction, spread threshold, target USD amount per side and slippage bound. Direction remains fixed; waiting does not swap the chosen accounts.

The common quantity is the long target divided by the executable long-side price, floored to a quantity step valid on both venues. Native minimum quantity/notional and inventory checks apply. Entry spread uses executable depth for that quantity:

```text
spread_pct = (short_sell_price / long_buy_price - 1) × 100
```

Entry requires `spread_pct >= threshold_pct`. Available collateral must cover the target amount per leg; the strategy uses existing venue leverage/margin settings rather than configuring them.

The first long order is journaled and sent once. Its confirmed filled quantity determines the short order's quantity after the short venue's step check. No confirmed first fill means no second leg. Partial or mismatched fills retain actual allocations, report the exposure and stop new strategy actions; the runtime does not automatically compensate, top up or add a missing leg.

## Close and reopening

Close first compares native inventory with all bot allocations for each account/symbol, then sends reduce-only orders for this bot's quantity. Residual inventory remains allocated if a close is partial.

Optional reopening starts its interval after both entry legs are confirmed. When due, it closes the allocated pair. Only fully confirmed closure advances the cycle. A uniformly sampled integer delay from 0 to `reopen_random_wait_seconds` is persisted, then the original spread condition is checked again. The random upper bound is at most 300 seconds.

Pause keeps inventory and disarms the reopen interval. Run with a matched pair starts a fresh interval. Manual Close ends the cycle. A temporary read outage before any order journal can skip and retry an automatic action; unknown or partial writes query the original operation and never start a replacement cycle.

## State and sharing

Each cycle has one original entry operation identity. Compatible same-direction spread bots can share a native account/symbol, but allocations and Close remain bot-specific. Conflicting directions, a grid reservation, external inventory, open native orders and unresolved local orders block new actions.

Tests: [runtime](../tests/test_runtime.py), [reopening](../tests/test_reopening.py), [read outages](../tests/test_read_outages.py), [lifecycle](../tests/test_lifecycle.py). Native protocol evidence: [Arcus/Lighter](research/native-execution.md), [Entropy](research/entropy.md).
