# Grid implementation references

Verified 2026-10-13 against public source. No private trading project was used.

## Hummingbot (primary reference)

Pinned `hummingbot/hummingbot` commit `9af100d6822da7d2d0291a906c730ef172284ee2`, Apache-2.0:

- [GridExecutor](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/strategy_v2/executors/grid_executor/grid_executor.py): grid geometry, quantized per-level sizing, budget/minimum-order checks, separate entry/close handling and fill-based metrics.
- [GridLevel](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/strategy_v2/executors/grid_executor/data_types.py): explicit entry/exit lifecycle, completed levels reset only after evidence.
- [Distributions.linear](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/strategy_v2/utils/distributions.py): actually adapted into `hummingbot_grid.py`; Decimal inputs retain exact configured price geometry. License and attribution are redistributed.
- [Official Grid Strike guide](https://hummingbot.org/blog/strategy-guide-grid-strike/): long/short perpetual grids and one-way position mode.

The complete executor imports Hummingbot connectors, strategy framework, tracked-order events and triple-barrier risk management. The previously inspected connector has no Arcus support or explicit RH profile. Installing it does not replace our pilot adapters. We reuse the pure geometry function and reference its sizing, entry/close and fill-accounting separation, while reusing this application's actual official Lighter signer and existing native execution journal. We do not claim to run Hummingbot's executor or inherit its funded acceptance.

Explicit differences: user fixes grid count; insufficient per-grid size fails instead of increasing budget/reducing the requested count. Quantity is computed conservatively at the upper boundary. Price-triggered IOC orders replace resting orders. There is no stop-loss, trailing stop, account-wide liquidation or automatic resubmission. Neutral signed inventory and the durable cursor are application-specific additions.

## Secondary comparison

[jordantete/grid_trading_bot](https://github.com/jordantete/grid_trading_bot/tree/262424be908227bab0587d9ff185157ea3180f20), commit `262424be908227bab0587d9ff185157ea3180f20`, MIT. Reviewed `grid_manager.py`, `grid_strategy.py`, `grid_level.py`: explicit geometry recovery, adjacent buy/sell pairing and state changes after completed orders. Its fiat/crypto initial-allocation model is not proof of perpetual signed-position ownership; its hedged strategy is not automatically our neutral mode. Reference only, no source copied.

## Native order type

[Arcus place-order contract](https://docs.arcus.xyz/api-reference/exchange/place-order.md) confirms IOC never rests and requires future goodTilTime. The pinned [official Lighter signer](https://github.com/elliottech/lighter-python/blob/04bee9ba9811b87ef1cccc568e7f590b5fe649bb/lighter/signer_client.py) distinguishes LIMIT IOC (expiry 0) from good-till-time. The grid uses the existing verified IOC signing path. It does not label an acknowledgement as a fill or imply orders remain on the exchange when this application stops.

Full resting-order grids would require persistent active-order/partial-fill accounting and journaled cancellation, which are not claimed by this first implementation.

## Binance behavior comparison

Checked official documentation on 2026-10-13:

- [Binance Futures grid guide](https://www.binance.com/en/academy/articles/step-by-step-guide-to-grid-trading-on-binance-futures) describes a configured price range with limit orders at predefined levels. After a buy fills, the system places a sell above; after a sell fills, it places a buy below. This replenishes orders after fills rather than redrawing every level on each price update.
- [Trailing Up / Trailing Down](https://www.binance.com/en/support/faq/detail/7a7bb22420404385991dee3a0930207d) is an optional mode that moves the range when its trailing conditions are met; it requires explicit trailing limits. Fixed geometry and exchange-resting order execution are separate choices.

This application currently retains fixed geometry but submits IOC only after an executable quote triggers a level. It is not Binance-style resting-order execution and has no trailing-range option. No Binance source code was copied.
