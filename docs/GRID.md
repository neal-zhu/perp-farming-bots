# Fixed price-triggered grid

Strategy ID: `grid`. Planner: [grid.py](../src/perp_farming_bots/grid.py). Parameters: `GridParameters` in [models.py](../src/perp_farming_bots/models.py). Form: [grid_ui.py](../src/perp_farming_bots/grid_ui.py).

## Geometry and sizing

A fixed arithmetic range has `N = grid_count` intervals and `N + 1` ascending levels. Levels use the attributed [Hummingbot geometry adaptation](../src/perp_farming_bots/hummingbot_grid.py), then native price precision. Collapsed or invalid levels are rejected.

Let `B = investment_usd × leverage`. This is the planned maximum notional within the configured range, not a turnover limit or an immediate transfer of margin. Each grid quantity is floored to the native size step:

```text
q = floor_to_step(B / (highest_level × sizing_units))
```

Long and short use `sizing_units = N`. Neutral uses the larger distance from the starting zero-inventory origin to either boundary. Save checks each order's minimum quantity/notional, account collateral, leverage/mode rules and account/symbol reservation. There is one capital model: `investment_usd`, integer `leverage`, and `margin_mode` (`cross` or `isolated`).

Run can apply native leverage/mode only to a flat account/symbol. The prepared setting is journaled, sent once and read back before activation. Unconfirmed settings block trading; subsequent synchronization only reads the original target. Investment remains a sizing budget; isolated margin follows actual native allocations and cross mode shares account collateral. No automatic margin top-up is performed.

## Startup and target inventory

The first eligible in-range price chooses the nearest level as the initial cursor `k`. The durable layout stores levels, `q`, cursor and the zero-inventory origin `a`.

| Direction | Origin when startup position enabled | Origin when startup position disabled | Signed target inventory |
| --- | --- | --- | --- |
| Long | `N` | Initial cursor | `max(0, a - k) × q` |
| Short | `0` | Initial cursor | `min(0, a - k) × q` |
| Neutral | Not allowed | Initial cursor | `(a - k) × q` |

`open_position_on_start` is required in the API configuration. New forms set it to false. Long/short startup positions can aggregate multiple shares in one initial order. Disabled startup initializes a flat layout and waits for a price trigger. Neutral always starts flat.

An unseeded directional grid may use only part of the nominal budget because its initial origin limits how many levels can create directional inventory. A boundary with no usable entry direction waits rather than freezing an unusable layout. Long never creates a short target; short never creates a long target.

## Trigger and progression

From cursor `k`:

- Buy when executable asks reach level `k - 1`.
- Sell when executable bids reach level `k + 1`.
- Compute the adjacent target and trade only the signed inventory delta.
- Reductions use reduce-only. A direction change first passes through confirmed zero inventory.

Prices are bounded by configured slippage, native precision, the trigger line and the grid range. These are **IOC orders sent after a program-side trigger**, not resting exchange orders. The shared executor journals before sending and queries the original identity. Cursor progression requires the complete target inventory and applied native evidence. Partial or unknown results do not advance the cursor or automatically submit a replacement order.

The final pre-submission quote can invalidate a trigger or move outside the range. If no order was journaled, that action is recorded as skipped, while the cursor and actual inventory stay unchanged. The grid continues waiting and evaluates fresh conditions on a later tick; price movement does not count as an order failure or a connection outage. Any existing order journal blocks this skip, regardless of whether an acknowledgement was received.

An empty book side or insufficient displayed depth for the full planned quantity also waits without changing the cursor, shrinking the order or raising action-required alerts. The executor rechecks full-quantity depth on its final quote, including startup orders. These known liquidity conditions do not count toward the connection-outage timeout. A crossed snapshot is temporarily unavailable and must be replaced by a valid fresh quote; cached prices are not substituted for a failed refresh.

A terminal IOC cancellation with confirmed zero fills leaves an initialized grid's cursor, levels and inventory unchanged. Its order and operation records remain, and a later eligible tick checks fresh prices/account state and creates a new client order ID. The canceled request is never replayed. Arcus's explicit `REJECTED / IOC_CANCELED` response is treated as this cancellation; other rejections still pause for review. A zero-fill startup cancellation discards only the uncommitted layout and waits to initialize again. Synchronizing an interrupted order that proves canceled with zero fills pauses for explicit Run before any new execution.

After a complete fill, the cursor moves to the executed line; the neighboring line in the opposite direction becomes the next potential reversal. Repeated price oscillations can continue increasing and reducing inventory. The grid range does not move with price. Outside the range, positions remain and new grid actions wait.

## Pause, close, edits and restart

The grid exclusively reserves its native account/symbol. External positions or orders and incompatible bot allocations block execution. Pause keeps layout and inventory. Run after Pause checks the original target and continues that layout. Close handles only owned quantity; after confirmed closure an explicit Run starts a new layout and retains historical turnover.

Flat paused/closed grids without unresolved operations can change direction, bounds, grid count, startup choice and capital. Historical orders lock account/symbol bindings. Save revalidates and clears only the current layout, with no trade; name/slippage-only edits preserve it.

Healthy service restart retains the initialized layout. Interrupted operations query original identities; recovered complete evidence pauses for explicit user resumption. An unsent operation can be skipped only if it has no order journal. Temporary native read failures retry; five minutes of continuous unavailability pauses the bot. Unknown writes remain in original-order recovery.

Synchronization also distinguishes an interrupted action with no order journal from an incomplete fill. It preserves the operation record, verifies the existing initialized layout against owned inventory (or discards only an uncommitted, empty startup layout), and pauses for explicit Run. It does not compare the unsubmitted next target against current inventory or submit a replacement. Native inventory and account settings are checked again on Run.

## Presentation and verification

The grid overview leads with trading PnL and configured collateral budget, then separates realized price PnL, unrealized PnL and fees. Trading PnL excludes actual funding; its percentage divides by the current configured budget and changes if that budget is edited. The budget is not native used/isolated collateral. Range, grid count, per-grid quantity, owned inventory, entry price and turnover remain separate fields. No matched-pair profit, matched-cycle count, liquidation price or risk score is inferred. Unknown money and unpublished/uninitialized values remain explicit.

The monitor keeps current price, nearest buy/sell triggers and distances visible. The grid plan is collapsed initially. Expanded red/green rows are conditional sell/buy plans; the blue row is current midpoint. Nearby rows appear by default, with an all-lines toggle. Uninitialized configurations do not display generated lines. Polling preserves expansion, rows, visibility and unsaved forms.

Tests: [grid execution](../tests/test_grid.py), [unfilled IOC recovery](../tests/test_grid_unfilled.py), [startup](../tests/test_grid_startup.py), [preflight](../tests/test_grid_preflight.py), [reuse and edits](../tests/test_grid_reuse.py), [quote outages](../tests/test_grid_quotes.py), [liquidity waits](../tests/test_liquidity_waits.py), [strategy presentation](../tests/test_strategy_widgets.py). Reuse evidence and notices: [grid research](research/grid.md), [UPSTREAMS.md](../UPSTREAMS.md).
