# Current implementation status

Updated 2026-10-13 (Asia/Shanghai). The application now uses native exchange accounts and orders. Generated market data, virtual balances and local execution have been removed from the application.

## Implemented

- Browser account onboarding: Arcus Ed25519 API Signing Key, wallet and subaccount; Lighter Core/RH API key and account indices.
- Verification before saving an account; encrypted local API-key storage and credential-free list responses.
- Explicit native identities, including multiple Arcus subaccounts on one wallet and multiple accounts on one venue.
- Native public market catalogs and order books for Arcus, Lighter Robinhood and Lighter Core.
- IOC limit orders, price bounds, market precision and reduce-only close.
- Signed requests persisted before submission; original client identity lookup after lost acknowledgements and restart. Unknown orders block further submission.
- Second-leg sizing from first-leg confirmed fills; partial and unmatched inventory remains visible and raises alerts. No automatic risk trading.
- Per-bot fill attribution and allocated inventory; closing one bot does not close another bot's quantity.
- Three primary trading controls: run (also resume), pause, and close. No separate stop action. Legacy schema 2 stopped states migrate explicitly without execution; uncertain inventory/journals remain attention.
- Optional scheduled reopening: confirmed entry starts the holding timer; confirmed reduce-only close advances the cycle and persists a random wait of 0 to the configured maximum (at most five minutes). The next entry still requires the original spread. Pause disarms the timer, resuming held inventory starts a new interval, and manual close ends the loop. Partial/unknown close outcomes never trigger automatic reentry.
- Per-bot cumulative confirmed turnover across all legs and cycles; unresolved orders keep the total explicitly unknown. Late fee enrichment is scoped to the current entry operation and cannot alter a later cycle's inventory.
- Bounded GET retry for transport failures and HTTP 502/503/504, shared by venue and points reads. One retry after 0.5 seconds, total budget 20 seconds; submissions are never resent. Diagnostics retain safe metadata and exclude credentials and native IDs. Notifications remain explicitly historical.
- Durable account points samples and 24-hour/seven-day/30-day ECharts history views. Exact decimals, failures and native account scopes survive restarts; read failures and unobserved intervals remain visual gaps.
- Bot editing and confirmed deletion in the browser/API, with server-side inventory/order checks. Entry parameter edits require an explicit restart of a waiting bot.
- Official hourly funding forecasts, last settlement rates, next payment times and payment directions for all three supported profiles. Missing data stays unavailable; funding attribution to actual bot PnL remains separate.
- Account-name inline validation, one persistent account form per page and duplicate-verification prevention.
- Bounded original-order confirmation polling after transient network/HTTP errors or incomplete reads; no order resubmission. Permanent identity errors remain unknown and stop the peer leg. Operation diagnostics survive background synchronization.
- Lighter zero trading fees are confirmed from authenticated, exact-order trade rows and native zero-field omission rules. Missing fees can be enriched later without reapplying fills or changing inventory. Optional fee reads do not block confirmed-fill recognition.
- Persistent Bot cards and alert rows: periodic updates change text and visibility in place, preserving form drafts and Telegram settings. Unmatched allocated legs are highlighted.
- Compact bot trading panels: fee-adjusted trading PnL is explicitly labeled as excluding funding; price PnL and fees remain visible. Two aligned position rows show account, native quantity, entry and forecast funding. Lifecycle controls stay prominent, edit/delete use the More menu, and full strategy/data details fold without losing state during refresh. Unknown values stay explicit and rounded negative zero is normalized.
- Official points reads: only the RH account's own live total. Cumulative/weekly/referral statistics have been removed; Core own-live-points access is explicitly unsupported until verified. Separate two-minute read task, manual refresh, per-metric unknown/error/stale states and persistent cards. Distinct sources are not added or attributed to bots. Arcus points are explicitly deferred by product decision; no session-token configuration or points requests remain.
- Actual account snapshots, stale/unavailable states, price PnL, explicit missing fees/funding/points, alerts and optional Telegram.
- Native database schema 4 in app.live.db. Schema 2/3 migrates explicitly with scheduled reopening disabled for existing bots. Prior records in app.db are preserved and are not treated as native evidence.
- Local password-free access, with security/login design deferred by product decision.

## Validation

- The updated Docker image built on Linux ARM64 and passed native-mode startup, homepage, catalog and empty-account HTTP checks.
- 129 automated tests passed, with ruff and mypy. Tests use isolated exchange doubles and independently constructed protocol fixtures, never production credentials.
- Browser verification: the native account workbench and Arcus connection form render; no generated/demo account entry is present. Local HTTP home and health return 200 on port 8088.
- Actual Arcus, Lighter RH and Lighter Core market catalogs and BTC books were read successfully with certificate verification enabled. Platform TLS uses the operating system trust store.
- Actual public funding reads succeeded for all three profiles. Tests check fractional/percentage units, native market identity, timestamps, unknown data, editing/deleting restrictions and real UI form callbacks.
- Read-only authenticated RH points queries succeeded on the user's existing account. Arcus's separate official account-points service returned 401 without its official login identity token. Points fixtures verify native hosts/account indices/auth headers, exact zero, malformed/missing values, account isolation, rate limiting, stale data and persistent UI drafts. No real orders are sent for points verification.
- The local points page and manual refresh were verified with actual RH counts; Arcus displays deferred status. Service update preserved the current bot state, parameters, positions and all order/operation journals. Temporary Arcus points authorization was removed from local settings and no Arcus points request path remains.
- The redesigned bot panel was checked in the actual browser: full-width styling, aligned position rows, readable status labels, edit menu/form and expanded data details. The service update preserved bot state, parameters, inventory and journals; no trading action was clicked.
- A live Core/RH funding probe revealed roughly 70 ms of upstream clock lead, incorrectly rejected as expired. Funding reads now allow a bounded five-second clock difference, still reject snapshots older than 60 seconds and expired settlements, and distinguish excessive future timestamps from stale data. Fixed-clock native-pattern regression tests cover both profiles.
- Scheduled-cycle tests cover original spread gating after random delay, multi-bot ownership, all-cycle turnover, pause/resume, manual termination, partial/unknown/preflight close failure, persistent deadlines and explicit schema migration. Points history tests cover exact decimals, explicit zeros/failures, scoped ranges, restart persistence and preserved chart controls.
- The actual browser shows cumulative confirmed turnover ($198.99 for the existing bot), configurable reopening and random-delay fields, and an RH points curve with real samples. Automatic samples arrived about 120 seconds apart. An actual restart preserved points history, bot cycles, inventory, original parameters and all native journals. The schema 3 database was backed up before migration; existing bots retain disabled reopening, and no live trading control was submitted during verification.
- Network investigation correlated 13 transport-warning timestamps with host power events; current Arcus/RH public probes and account reads succeeded. Regression tests cover transient recovery, bounded exhaustion, total timeout, auth/rate-limit behavior, single-submit writes, diagnostic redaction and exact-decimal points history.
- Arcus typed signing payload is verified with the actual Ed25519 public key; timestamps, expiry, price ticks, quantity quantums and case-sensitive client identity are checked.
- Lighter tests verify explicit Core/RH chain IDs, nonce, IOC expiry, reduce-only and native-order identities. The application uses the pinned official signer SDK.
- Runtime tests cover independently closing multiple bots, partial first/peer/close fills, unknown outcomes, lost send ACK, repeated synchronization, restart, stale quotes, external inventory and external open orders.

Development tests use isolated test credentials and send no real orders. The user has connected accounts themselves through the local UI. Funded round-trip trading still awaits user-controlled venue acceptance. Passing fixture tests and public reads does not certify native execution.

A user-controlled entry revealed a first-leg confirmation failure, followed by later first-leg fill evidence and no second-leg journal. The original read exception was not retained, so its precise native cause cannot be certified. Tests reproduced the runtime defect: one temporary query error aborted confirmation immediately. Confirmation polling and diagnostic retention were corrected. Existing unmatched inventory remains unchanged by this fix; synchronization does not automatically submit a missing peer leg.

## Remaining

- Actual private-account and funded-order acceptance for each supported profile.
- Complete long-range paginated order/fill history and WebSocket reconciliation.
- Arcus points (deferred by product decision); Core own-live-points endpoint verification; bot-specific funding attribution; Lighter nonzero fee monetary accounting.
- Hyperliquid/Binance native accounts and orders; additional venues.
- Grid/scalping specification and implementation.
- Security/login design and release packaging validation on additional platforms.

This is a single-process application with ordinary SQLite transactions. There is no distributed failover or claim of atomic cross-exchange fills.
