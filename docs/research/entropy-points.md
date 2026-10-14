# Entropy account points investigation

Verified 2026-10-14 against official documentation and the public Entropy frontend. No private repository code, authenticated account data, credentials, wallet signatures or funded actions were used.

## Result and implementation boundary

A supported Entropy account-points endpoint, authoritative point field, period definition and refresh authorization could not be verified. This investigation does not establish that an internal or future points program cannot exist. It establishes that the reviewed public sources do not provide enough evidence to implement official account points or a points-history curve.

Entropy remains explicitly unsupported for automatic points collection. Missing data must not become `0`, and trading volume, fee rebates or referral rewards must not be relabeled as points.

## Official reward meaning

The [official Referrals documentation](https://docs.entropy.io/about-entropy/referrals) defines monetary self rebates, rewards from referred users' fees and a referred-user fee benefit. Eligibility applies to Entropy-deployed markets for addresses that previously connected to Entropy and created an account; the trading frontend is not restricted. Percentages use Entropy's share of HIP-3 fees. Rewards are reviewed and claimed separately. These are fee benefits, not an authoritative point balance.

The [official documentation index](https://docs.entropy.io/llms.txt) lists architecture, referrals, market mechanics, assets, margin and legal pages; the retrieved index contains no points specification. This is evidence about that index, not proof that no other service exists.

## Reviewed official frontend

Assets were discovered from [Entropy's published entry point](https://entropy.io/) and its dependency lists. They were inspected for API contracts only; no frontend code was copied into the application. Hashed asset URLs can change when Entropy deploys.

| Official source | Verified contract or field meaning |
| --- | --- |
| [Referral API helpers](https://entropy.io/assets/downline-stats-D7xU6PTi.js) | Reads `/api/referrals/program`, `/tier`, `/earnings`, `/attribution`, `/payouts`, `/activity` and `/referred-users`. The common prefix is `/api/referrals`. The inspected helper has no points balance request. |
| [Referral page](https://entropy.io/assets/Referrals-6PDLxl1w.js) | Activity scopes are `referrals` and `cashback`. Native fields include `qualifyingTrades`, `volumeUsd`, `estimatedRebate` and reward statuses. These cannot define points. |
| [Referral API helpers](https://entropy.io/assets/downline-stats-D7xU6PTi.js) | Approved monetary earnings combine `approved` and `cashback.approved`; claimed earnings combine `claimed` and `cashback.claimed`. Activity uses `series`, `bucket`, `windowStart`, `windowEnd`, `window` and `bucketUnit`; daily windows use hourly buckets, all-time windows monthly buckets, otherwise daily buckets. These are reward/activity dimensions, not point seasons. |
| [Leaderboard page](https://entropy.io/assets/Leaderboard-El0p9ep1.js) | Authenticated standing reads `/api/users/me/leaderboard` with `window`, `metric`, `scope=all-perps` and `computedAt`. Displayed metrics are realized PnL, unrealized PnL and volume. Rankings are not points. |
| [Profile page](https://entropy.io/assets/Profile-DNgaTKM4.js) | The inspected wallet-profile schema defines wallet identity, account balance, DEX scopes, positions and recent-history freshness/capping. No point total or current-period point field appears in that schema. |

No verified total-points/current-period-points relationship, season identifier, point history, update cadence or point reset behavior was found. A curve cannot be calculated from the reviewed monetary/activity fields.

## Authorization and probes

The [official API wrapper](https://entropy.io/assets/api-DrEzcQ67.js) gets a session token and attaches `Authorization: Bearer …` to authenticated requests. Its separate optional-auth wrapper may omit the token for public requests. The [official Privy integration](https://entropy.io/assets/entropy-trade-DtU8l9j7.js) installs Privy's `getAccessToken` as that token getter. These are website-session credentials; the inspected code does not expose a points API authenticated by a Hyperliquid trading-agent key.

The reviewed referral page keys requests by signed-in user ID or wallet address. It does not establish an arbitrary-address points query or an API-agent mechanism for reading another configured account's reward data. No authenticated business response or token-refresh flow was exercised.

Unauthenticated command-line probes of the discovered referral reads and leaderboard standing, plus the unverified `/api/points` path, returned Cloudflare HTTP 403 / error 1010 (`browser_signature_banned`). These responses came from the edge, not a verified business API. They establish neither endpoint existence nor an account's point balance. The blocked probes were not retried, and no anti-bot bypass was attempted.

Integration requires an official, verifiable points response and account authorization contract. Until those are available, the application should retain its existing explicit unsupported state.
