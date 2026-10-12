# Official points reads

Independently checked on 2026-10-12 (Asia/Shanghai). No private project supplied code or protocol evidence. All requests below are read-only, with no referral registration, reward claim, wallet login or trade submission.

## Lighter Robinhood

- [Official live-points endpoint](https://apidocs.rh.lighter.xyz/reference/livepoints_total.md): GET `/api/v1/livePoints/total`, required `account_index`, optional `authorization` header. Successful schema requires `code=200` and numeric `total_live_points`. The application uses the existing account API key to generate the native authorization token and shows this field as account-scoped real-time total.
- [Official points statistics endpoint](https://apidocs.rh.lighter.xyz/reference/referral_points.md): authenticated GET `/api/v1/referral/points` for `account_index`. The successful schema has **no required code field**. `user_total_points` and `user_last_week_points` are shown as official cumulative and last-week statistics. `user_total_referral_reward_points` and third-party `referrals` are separate fields and are not substituted for the user's own statistics.
- [Program description](https://docs.lighter.xyz/points-program/lighter-on-robinhood-chain-points.md) describes real-time points plus weekly awards. The API documentation does not establish an additive relationship between the two endpoints. Do not add the displayed totals together or infer undisclosed subaccount aggregation. Displaying a count is not certification of program eligibility or future rewards.

Read-only authenticated requests for the user's existing RH account succeeded: live points were approximately 2.1376, while the cumulative and last-week statistics both explicitly returned numeric zero. These are observed API values, not transaction-volume estimates. No real order was submitted.

## Lighter Core

[Core's official points statistics endpoint](https://apidocs.lighter.xyz/reference/referral_points.md) documents the same authenticated statistics fields. It is queried on `https://mainnet.zklighter.elliot.ai`, using Core's native signer domain, never RH's host/token. No documented Core live-total endpoint was found in its [API index](https://apidocs.lighter.xyz/llms.txt); no guessed endpoint is called. Cumulative/last-week counts are displayed as official statistics without claiming they are current-season farming accrual.

The [retail points description](https://docs.lighter.xyz/points-program/retail.md) is season-specific, and [market-maker documentation](https://docs.lighter.xyz/points-program/market-makers.md) records Season 2 ending on December 26, 2025. Historic statistics must not be presented as proof of an active Core points season. Core account reads still await validation with a user-connected Core account; protocol behavior is covered by isolated HTTP fixtures.

## Arcus deferred by product decision

The [official application](https://app.arcus.xyz/) uses a separate points service and Privy login identity token, rather than the trading API key. Endpoint/authentication semantics were researched from publicly served frontend assets; no source implementation was copied. An account request without the official identity token returned HTTP 401; a subsequent user-authorized query with their temporary token returned HTTP 200.

The user decided to defer Arcus points on 2026-10-12. All in-progress Arcus points request, authorization and token-storage code was removed, and the temporary saved authorization was removed from local settings. The application displays an explicit unsupported state and a link to [Arcus Rewards](https://app.arcus.xyz/rewards). It makes no Arcus points request and does not prompt for browser tokens or wallet signatures.

## Runtime and presentation

The dedicated read task polls every two minutes, independently of strategy execution. An explicit refresh button/API is available; requests within ten seconds are coalesced. Values and timestamps are cached in memory only. Successful data older than five minutes becomes explicitly unavailable. A failed refresh replaces the affected metric with an unknown value; it does not keep showing an old success as current or synthesize zero.

Metrics fail independently: a failed statistics endpoint does not erase a confirmed live total, and one failed account does not block others. JSON null, missing fields, booleans, strings, negative or nonfinite numbers fail explicitly. Authorization tokens stay in request headers and are never returned in the points API or raw error messages. Decimal parsing preserves native numeric precision.

Points remain attached to accounts with explicit scope metadata. No all-platform sum, bot allocation, daily earning estimate or PnL conversion is introduced. Persistent browser cards update their existing labels rather than reconstructing the page.
