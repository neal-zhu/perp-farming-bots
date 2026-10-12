# Official points reads

Independently checked on 2026-10-12 (Asia/Shanghai). No private project supplied code or protocol evidence. All requests below are read-only, with no referral registration, reward claim, wallet login or trade submission.

## Lighter Robinhood

- [Official live-points endpoint](https://apidocs.rh.lighter.xyz/reference/livepoints_total.md): GET `/api/v1/livePoints/total`, required `account_index`, optional `authorization` header. Successful schema requires `code=200` and numeric `total_live_points`. The application uses the existing account API key to generate the native authorization token and shows this field as account-scoped real-time total.
- [Program description](https://docs.lighter.xyz/points-program/lighter-on-robinhood-chain-points.md) describes real-time points plus weekly awards. The application displays the native account live-total field without estimating points or certifying reward eligibility.

Only the user's own account live total is queried and displayed. The earlier `/api/v1/referral/points` statistics returned zero for cumulative/last-week fields despite a positive live total. Their relationship to real-time account points was not established. Per the user's decision, cumulative, weekly and referral statistics and their request path have been removed from the runtime and UI. A missing live-total field remains unknown and never falls back to the old statistics.

Read-only authenticated live-total requests for the user's existing RH account succeeded. No real order was submitted.

## Lighter Core

No documented Core account live-total endpoint was found in its [API index](https://apidocs.lighter.xyz/llms.txt). Core therefore displays an explicit unsupported state; no Core points request is sent and no statistics endpoint is used as a replacement. Its existing trading/account execution path is unaffected.

## Arcus deferred by product decision

The [official application](https://app.arcus.xyz/) uses a separate points service and Privy login identity token, rather than the trading API key. Endpoint/authentication semantics were researched from publicly served frontend assets; no source implementation was copied. An account request without the official identity token returned HTTP 401; a subsequent user-authorized query with their temporary token returned HTTP 200.

The user decided to defer Arcus points on 2026-10-12. All in-progress Arcus points request, authorization and token-storage code was removed, and the temporary saved authorization was removed from local settings. The application displays an explicit unsupported state and a link to [Arcus Rewards](https://app.arcus.xyz/rewards). It makes no Arcus points request and does not prompt for browser tokens or wallet signatures.

## Runtime and presentation

The dedicated read task polls every two minutes, independently of strategy execution. An explicit refresh button/API is available; requests within ten seconds are coalesced. Values and timestamps are cached in memory only. Successful data older than five minutes becomes explicitly unavailable. A failed refresh replaces the affected metric with an unknown value; it does not keep showing an old success as current or synthesize zero.

One failed account does not block other accounts' points reads. JSON null, missing fields, booleans, strings, negative or nonfinite numbers fail explicitly. Authorization tokens stay in request headers and are never returned in the points API or raw error messages. Decimal parsing preserves native numeric precision.

Points remain attached to accounts with explicit scope metadata. No all-platform sum, bot allocation, daily earning estimate or PnL conversion is introduced. Persistent browser cards update their existing labels rather than reconstructing the page.
