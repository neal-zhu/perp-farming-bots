# Cross-account spread hedging

Strategy ID: `spread_hedging`. Implementation: [runtime.py](../src/perp_farming_bots/runtime.py). Parameters: `HedgeParameters` in [models.py](../src/perp_farming_bots/models.py).

## Entry

Bind two different account instances. Select `long_symbol` and `short_symbol` independently from their venues’ active perpetual catalogs, plus the spread threshold, target USD amount per side and slippage bound. No cross-venue asset-equivalence validation is performed. Direction and ticker remain fixed; waiting does not swap them.

Each preview quantity is the target USD amount divided by that leg’s native price, floored to that market’s quantity step. Native minimum quantity/notional and inventory checks apply independently. Entry spread compares the selected contracts’ executable prices directly:

```text
spread_pct = (short_sell_price / long_buy_price - 1) × 100
```

Entry requires `spread_pct >= threshold_pct`. Available collateral must cover the target amount per leg; the strategy uses existing venue leverage/margin settings rather than configuring them.

The first long order is journaled and sent once. Its confirmed fill notional (quantity × average price) determines the short order’s quantity, divided by the short quote and floored to that market’s step. No confirmed first fill means no second leg. A confirmed partial first fill can form a pair when the second leg fills its adjusted plan. Unequal contract quantities are expected; completion, resume, closing and reopening validate each leg against its own journal. Partial second fills retain actual allocations, report the exposure and stop new strategy actions; the runtime does not automatically compensate, top up or add a missing leg.

Both planning and the final quote require displayed depth for the full requested quantity. If a book side is empty or depth disappears before the first order journal, entry keeps waiting without changing size. If the first leg already filled and the second leg loses depth, the bot retains the confirmed exposure and requires review; it does not replay the first order or automatically add a missing leg.

## Close and reopening

Close first compares native inventory with all bot allocations for each account/symbol, then sends reduce-only orders for this bot's quantity. Residual inventory remains allocated if a close is partial.

Optional reopening starts its interval after both entry legs are confirmed. When due, it closes the allocated pair. Only fully confirmed closure advances the cycle. A uniformly sampled integer delay from 0 to `reopen_random_wait_seconds` is persisted, then the original spread condition is checked again. The random upper bound is at most 300 seconds.

Pause keeps inventory and disarms the reopen interval. Run with a fully confirmed pair starts a fresh interval. Manual Close ends the cycle. A temporary read outage before any order journal can skip and retry an automatic action; unknown or partial writes query the original operation and never start a replacement cycle.

Insufficient depth before any close order journal leaves a scheduled close waiting with its interval intact. A manual Close that cannot submit pauses and asks the user to Close again after recovery; it does not schedule a delayed trade. Once a close order has been journaled, original-order evidence takes precedence and no liquidity-based retry bypasses it.

## State and sharing

Each cycle has one original entry operation identity. Compatible same-direction spread bots can share a native account/symbol, but allocations and Close remain bot-specific. Conflicting directions, a grid reservation, external inventory, open native orders and unresolved local orders block new actions.

Tests: [independent ticker selection](../tests/test_market_selection.py), [runtime](../tests/test_runtime.py), [reopening](../tests/test_reopening.py), [read outages](../tests/test_read_outages.py), [lifecycle](../tests/test_lifecycle.py). Native protocol evidence: [Arcus/Lighter](research/native-execution.md), [Entropy](research/entropy.md).
