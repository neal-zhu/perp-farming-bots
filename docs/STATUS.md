# Implementation status

Updated 2026-10-14 (Asia/Shanghai).

## Supported features

- Multiple native account instances and multiple independent bots. Arcus, Lighter Core and Lighter Robinhood use distinct verified native identities.
- Cross-account spread hedging, including different accounts on one venue. The second leg is sized from the first leg's confirmed fill.
- Optional timed hedge reopening, with a durable random delay of up to five minutes and spread checks before each entry.
- Fixed arithmetic perpetual grids in long, short and neutral directions. Price-triggered IOC execution requires the program to remain online.
- Grid sizing by investment-margin budget, integer leverage and cross/isolated mode. Save validates native rules, minimum orders, collateral and inventory; Run confirms native settings before activation.
- Per-bot allocated positions, real fills, confirmed turnover, trading PnL, fees and separate funding forecasts. Unknown values remain explicit.
- Run, Pause and Close controls, parameter editing and confirmed deletion. Flat paused/closed grids can change strategy parameters. Historical execution fixes account/symbol bindings.
- Original-order recovery after lost acknowledgements and restart, without automatic order resubmission or portfolio risk trading.
- Temporary quote outages skip trading and retain the selected running state. Uncertain orders or partial inventory block new actions until resolved.
- Robinhood account points sampling every two minutes and 24-hour, seven-day and 30-day history curves. Missing samples remain gaps.
- Persistent panels with local updates, inline form validation, in-app alerts and optional Telegram notifications.
- Database format 7. Grid capital has one structure: investment, leverage and margin mode. Unsupported database/configuration formats fail explicitly; no conversion branches are included.

## Validation

Automated tests use isolated venue doubles and credentials. Checks cover ownership, minimum orders and collateral, native margin units, journal-before-send, original-order reconciliation, partial/unknown fills, quote freshness, parameter-edit restrictions, points history and browser form callbacks. Passing these tests is not a claim of funded execution acceptance.

Run `make check` and `make test` to validate the current checkout. Public and authenticated read capabilities are documented in [native-execution.md](research/native-execution.md), [margin.md](research/margin.md) and [points.md](research/points.md). Public code reuse and notices are recorded in [UPSTREAMS.md](../UPSTREAMS.md).

## Remaining work

- Independent funded-order acceptance for each venue/profile.
- Long-range paginated order/fill history and WebSocket reconciliation.
- Bot-attributed funding payments and Lighter nonzero fee monetary accounting.
- Arcus/Core account points integration.
- Additional exchange adapters, exchange-resting grids and scalping strategies.
- Login/access design and packaging validation on additional platforms.

The application uses one process and SQLite transactions. Cross-exchange fills are not atomic.
