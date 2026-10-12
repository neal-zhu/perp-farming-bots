# Current implementation status

Updated 2026-10-12 (Asia/Shanghai). The application now uses native exchange accounts and orders. Generated market data, virtual balances and local execution have been removed from the application.

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
- Bot editing and confirmed deletion in the browser/API, with server-side inventory/order checks. Entry parameter edits require an explicit restart of a waiting bot.
- Official hourly funding forecasts, last settlement rates, next payment times and payment directions for all three supported profiles. Missing data stays unavailable; funding attribution to actual bot PnL remains separate.
- Account-name inline validation, one persistent account form per page and duplicate-verification prevention.
- Bounded original-order confirmation polling after transient network/HTTP errors or incomplete reads; no order resubmission. Permanent identity errors remain unknown and stop the peer leg. Operation diagnostics survive background synchronization.
- Lighter zero trading fees are confirmed from authenticated, exact-order trade rows and native zero-field omission rules. Missing fees can be enriched later without reapplying fills or changing inventory. Optional fee reads do not block confirmed-fill recognition.
- Persistent Bot cards and alert rows: periodic updates change text and visibility in place, preserving form drafts and Telegram settings. Unmatched allocated legs are highlighted.
- Official points reads: RH account live total, plus Core/RH cumulative and last-week statistics. Separate two-minute read task, manual refresh, per-metric unknown/error/stale states and persistent cards. Distinct sources are not added or attributed to bots. Arcus points are explicitly deferred by product decision; no session-token configuration or points requests remain.
- Actual account snapshots, stale/unavailable states, price PnL, explicit missing fees/funding/points, alerts and optional Telegram.
- Native database schema 3 in app.live.db. Prior records in app.db are preserved and are not treated as native evidence.
- Local password-free access, with security/login design deferred by product decision.

## Validation

- The updated Docker image built on Linux ARM64 and passed native-mode startup, homepage, catalog and empty-account HTTP checks.
- Eighty-six automated tests passed, with ruff and mypy. Tests use isolated exchange doubles and independently constructed protocol fixtures, never production credentials.
- Browser verification: the native account workbench and Arcus connection form render; no generated/demo account entry is present. Local HTTP home and health return 200 on port 8088.
- Actual Arcus, Lighter RH and Lighter Core market catalogs and BTC books were read successfully with certificate verification enabled. Platform TLS uses the operating system trust store.
- Actual public funding reads succeeded for all three profiles. Tests check fractional/percentage units, native market identity, timestamps, unknown data, editing/deleting restrictions and real UI form callbacks.
- Read-only authenticated RH points queries succeeded on the user's existing account. Arcus's separate official account-points service returned 401 without its official login identity token. Points fixtures verify native hosts/account indices/auth headers, exact zero, malformed/missing values, partial failure, rate limiting, stale data and persistent UI drafts. No real orders are sent for points verification.
- The local points page and manual refresh were verified with actual RH counts; Arcus displays deferred status. Service update preserved the current bot state, parameters, positions and all order/operation journals. Temporary Arcus points authorization was removed from local settings and no Arcus points request path remains.
- Arcus typed signing payload is verified with the actual Ed25519 public key; timestamps, expiry, price ticks, quantity quantums and case-sensitive client identity are checked.
- Lighter tests verify explicit Core/RH chain IDs, nonce, IOC expiry, reduce-only and native-order identities. The application uses the pinned official signer SDK.
- Runtime tests cover independently closing multiple bots, partial first/peer/close fills, unknown outcomes, lost send ACK, repeated synchronization, restart, stale quotes, external inventory and external open orders.

Development tests use isolated test credentials and send no real orders. The user has connected accounts themselves through the local UI. Funded round-trip trading still awaits user-controlled venue acceptance. Passing fixture tests and public reads does not certify native execution.

A user-controlled entry revealed a first-leg confirmation failure, followed by later first-leg fill evidence and no second-leg journal. The original read exception was not retained, so its precise native cause cannot be certified. Tests reproduced the runtime defect: one temporary query error aborted confirmation immediately. Confirmation polling and diagnostic retention were corrected. Existing unmatched inventory remains unchanged by this fix; synchronization does not automatically submit a missing peer leg.

## Remaining

- Actual private-account and funded-order acceptance for each supported profile.
- Complete long-range paginated order/fill history and WebSocket reconciliation.
- Arcus points (deferred by product decision); Core private-account points acceptance; points history and bot-specific funding attribution; Lighter nonzero fee monetary accounting.
- Hyperliquid/Binance native accounts and orders; additional venues.
- Grid/scalping specification and implementation.
- Security/login design and release packaging validation on additional platforms.

This is a single-process application with ordinary SQLite transactions. There is no distributed failover or claim of atomic cross-exchange fills.
