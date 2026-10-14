# Official points reads

Independently checked on 2026-10-12 (Asia/Shanghai). No private project supplied code or protocol evidence. All requests below are read-only, with no referral registration, reward claim, wallet login or trade submission.

## Lighter Robinhood

- [Official live-points endpoint](https://apidocs.rh.lighter.xyz/reference/livepoints_total.md): GET `/api/v1/livePoints/total`, required `account_index`, optional `authorization` header. Successful schema requires `code=200` and numeric `total_live_points`. The application uses the existing account API key to generate the native authorization token and shows this field as account-scoped real-time total.
- [Program description](https://docs.lighter.xyz/points-program/lighter-on-robinhood-chain-points.md) describes real-time points plus weekly awards. The application displays the native account live-total field without estimating points or certifying reward eligibility.

Only the account live total is queried and displayed. Referral, weekly and cumulative statistics do not establish this metric and are not used as replacements. Missing or invalid live-total fields remain unknown.

## Lighter Core

No documented Core account live-total endpoint was found in its [API index](https://apidocs.lighter.xyz/llms.txt). Core therefore displays an explicit unsupported state; no Core points request is sent and no statistics endpoint is used as a replacement. Its existing trading/account execution path is unaffected.

## Arcus and Entropy exclusions

The [official Arcus application](https://app.arcus.xyz/) uses a separate points service with a Privy login identity token, rather than the trading API key. Authorization semantics were researched from public frontend assets; no implementation was copied. Trading API credentials do not establish authorization for this service. The application makes no Arcus points request, stores no browser session token and links to [Arcus Rewards](https://app.arcus.xyz/rewards).

Entropy account points are not integrated. Neither native Hyperliquid turnover nor the presence of an Entropy builder code is treated as evidence of an official points balance. Both providers return explicit unsupported values.

## Runtime and presentation

The dedicated read task polls every two minutes, independently of strategy execution. An explicit refresh button/API is available; requests within ten seconds are coalesced. Current snapshots remain in memory; each actual read persists its exact decimal value or explicit failure, native scope, sample timestamp and source in SQLite. The history API and persistent ECharts view support 24-hour, seven-day and 30-day windows. Failed samples remain null; unobserved gaps longer than five minutes break the line without inventing stored observations. Successful current data older than five minutes becomes explicitly unavailable. A failed refresh replaces the affected current metric with an unknown value; it does not keep showing an old success as current or synthesize zero. Restarting continues polling and preserves history.

One failed account does not block other accounts' points reads. JSON null, missing fields, booleans, strings, negative or nonfinite numbers fail explicitly. Authorization tokens stay in request headers and are never returned in the points API or raw error messages. Decimal parsing preserves native numeric precision.

Points remain attached to accounts with explicit scope metadata. No all-platform sum, bot allocation, daily earning estimate or PnL conversion is introduced. Persistent browser cards update their existing labels rather than reconstructing the page.
