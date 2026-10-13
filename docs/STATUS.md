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
- Native database schema 6 in app.live.db; schema 5 adds grid tables without changing existing bot data. Schema 2/3 migrates explicitly with scheduled reopening disabled for existing bots. Prior records in app.db are preserved and are not treated as native evidence.
- Local password-free access, with security/login design deferred by product decision.

## Validation

- The updated Docker image built on Linux ARM64 and passed native-mode startup, homepage, catalog and empty-account HTTP checks.
- 177 automated tests passed, with ruff and mypy. Tests use isolated exchange doubles and independently constructed protocol fixtures, never production credentials.
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
- Exchange-resting grid execution and scalping specification/implementation.
- Security/login design and release packaging validation on additional platforms.

This is a single-process application with ordinary SQLite transactions. There is no distributed failover or claim of atomic cross-exchange fills.

## Grid delivery (2026-10-13)

Long, short and neutral price-triggered perpetual grids are implemented for the three native profiles. The form previews actual per-grid quantity, initial signed inventory and capped maximum notional; grid accounts/symbols are exclusive. Durable geometry and cursor, weighted owned inventory, actual turnover/PnL, pause/resume, allocated reduce-only close and original-order recovery reuse the existing native journal. Hummingbot pure geometry is adapted with Apache-2.0 attribution; full-engine integration is not claimed.

Grid tests cover directional accumulation/reduction, neutral zero-before-reverse, interval boundaries, pause/resume, unknown and partial fills without resend, original synchronization, healthy restart, external inventory/orders, schema 4 preservation, locked geometry and budget validation. Tests send no venue orders. Funded grid acceptance remains user-controlled.

Local release backed up schema 4 and preserved the existing live hedge bot’s parameters, state, allocated inventory, original orders/fills/operations, turnover and user-selected reopening deadline exactly. The grid chooser and three-direction form were checked in the actual browser without saving or running a grid. Wheel includes upstream license/notice; Docker packaging includes the same files.

## Grid parameter preflight (2026-10-13)

A user-created ETH grid retained a BTC-scale price range after changing symbol and failed minimum-order checks only on run. Native rules confirmed the actual Arcus ETH minimum quantity/notional; its current account balance exceeded the selected $20 budget. An API regression reproduced invalid configuration saving with HTTP 201. The fix validates grid create/update in both browser and API before persistence, reuses the same checked preview at run, reports quantized minimum budget and fresh account funds, and excludes an edited bot from its own account reservation. Name/slippage-only edits to initialized grids preserve existing inventory without requiring the full budget as idle collateral again.

Symbol changes clear price bounds. Parameter changes invalidate previous previews, and late quotes cannot overwrite a newly selected symbol or manually edited range. Save fields remain disabled during native validation and are restored on failure without losing input. Tests cover early API/UI rejection, insufficient/unavailable funds, minimum precision, own-bot edit previews, holding edits and currency/late-response handling. No saved bot parameters or trading actions were changed for verification.

The updated local service preserved both existing bots’ configuration, states, allocated inventory, native journals and cycles. Read-only preview of the saved ETH/BTC-scale range rejects before submission; a same-account ETH preview at 2,260–2,770, six neutral grids and $20 passed with an exact minimum budget of $18.385044 and real available collateral. The browser showed the pre-save error and then the corrected range, quantities, minimum budget, fresh funds and check time. The corrected range remains an unsaved draft for the user; no run/save trading control was submitted.

## Simplified grid submission (2026-10-13)

The grid form now submits through one Save button. The redundant preview button and panel are removed; native parameter validation remains mandatory before browser/API persistence. While checking, Save shows a loading state and prevents duplicate submission. Failures appear next to Save and preserve entered values. Read-only API previews remain available for integrations and diagnostics. Currency changes and late-quote handling are unchanged.

All 161 tests passed, including the actual form callback rejecting an invalid budget without saving or losing input. Ruff and mypy passed. The local service update preserved both bots and all ten existing native order journals, inventory and cycle deadlines. Browser verification confirmed only Cancel and Save in the form footer; the ETH range draft was restored after reload and remains unsaved. No live trading action was submitted.

## Strategy-specific monitoring (2026-10-13)

Grid cards now show a persistent red/green price ladder using durable, native-quantized grid state. The wall labels conditional plans rather than resting exchange orders; only adjacent lines are highlighted. Current native midpoint is positioned in the ladder, trigger distances use executable bid/ask, and actions distinguish opening from reduce-only. Actual allocated inventory and confirmed fill count remain separate from planned lines. Zero-target neutral initialization, paused/closed states, outside-range quotes, stale prices and uncertain orders have explicit explanations. Uninitialized configs do not invent a native grid layout.

Hedge cards use the existing execution sizing/quote calculation to display current entry spread, threshold and target, plus scheduled close/random-wait countdowns. Preview evidence now includes the older native book timestamp so delayed UI reads cannot display an expired spread as current. Public observation reads do not call trading commands, alter bot state, or mutate trading journals. Form edits during a quote read discard the former configuration's observation.

Six new monitor tests cover zero-inventory waiting, long/short open-versus-reduce labels, stable row identities, paused and expired-data handling, uninitialized geometry, and hedge quote conditions without new orders.

All 167 tests, ruff and mypy passed; monitor tests additionally confirmed delayed quotes expire before rendering. The local service update preserved both bots, the initialized ETH cursor/quantity/levels, all ten existing native order journals, allocated inventory, configuration and cycle deadlines. Actual browser inspection showed the ETH ladder sorted by descending price with next-line highlights, a correctly positioned live price, an explicit zero-inventory explanation and updates in place. The hedge panel showed the native executable entry spread and a decreasing scheduled-close countdown. No trading control was clicked for verification.

## Reusing closed bots (2026-10-13)

A closed grid now offers an explicit rerun after confirmed flat inventory. It performs the native preflight before atomically clearing only active geometry and returning to waiting; prior orders, fills, action journals and cumulative turnover remain. The next strategy tick initializes from current prices. Pause/resume keeps its original cursor, and rerun never happens automatically. Old completed close synchronization cannot end a newly authorized run. Uncertain orders, remaining allocated inventory, stale quotes, external orders, insufficient funds or another bot's reservation prevent resetting the old state. Closed hedge bots similarly validate accounts and start a fresh cycle with an empty opening identity and no armed timer; the original spread condition still gates the next entry. A never-entered cycle is reused rather than manufacturing an extra completed cycle.

The wall heading is now “网格触发计划”; closed cards label their previous layout and explain reinitialization. Nine new tests exercise full and zero-target reruns, preserved evidence, old-close synchronization, preflight failures, inventory invariants, and an enabled UI control that does not activate execution by itself.

Lifecycle tests additionally verify an explicit hedge rerun uses a new cycle/order identity, preserves old journals, and keeps a failed preflight's closed state unchanged. Both strategies retain user-controlled execution; an application update does not activate closed bots.

All 177 tests, ruff and mypy passed. Local release preserved both user-closed bots, their parameters, the previous grid layout, cycles, turnover and all sixteen native order journals exactly. The browser shows enabled “重新运行” controls for both strategies and explains the new-run behavior; no control was clicked and both bots remain closed. Binance's official fixed-range/resting-order and optional trailing behavior is recorded in the grid research notes.

## Grid investment margin and leverage (2026-10-13)

New grids configure investment-margin budget, integer leverage and cross/isolated mode. Planned maximum notional inside the configured interval is investment × leverage, quantized grid quantity is derived from that notional, and funds checks use the margin budget. Save reads market leverage limits, precise units, minimum orders and available collateral without applying settings. Run journals an encrypted native configuration before a single submission and requires fresh actual leverage/mode readback. Lost ACKs are resolved by reads; bounded unconfirmed results remain unknown, block activation and recover paused for explicit user resumption. Active setting changes block new strategy actions, while manual allocated reduce-only close remains available.

Arcus uses its native effective-leverage API and documented nanosecond/legacy setLeverage signature. Lighter Core/RH use separate pinned SDK chain profiles, integer IMF for signing and percent IMF for account reads. Unrepresentable leverage is rejected; a missing native account/market row remains unknown. The form and grid monitor show actual venue leverage/mode and market maximum independently of the planned strategy budget. Investment is a quantity budget, not an upfront reservation of all funds; no automatic margin top-up is added.

Schema 6 explicitly migrates old grid budgets to notional capital without multiplying quantity or setting leverage. Confirmed flat closed grids can convert capital mode without changing binding/geometry configuration or deleting trading history. Migration preserves existing initialized levels, cursor, quantity, positions, cycles, journals and turnover. Protocol evidence is recorded in research/margin.md.

All 202 isolated tests passed, including native unit decoding and exact profile/signatures, read-only saving, funds sizing, encrypted journal before send, lost ACK confirmation, total read timeout, unknown recovery without resend, external setting mismatch with manual close, legacy migration and capital conversion. Ruff and mypy passed. No funded margin-setting submission was used for verification.

Local release backed up schema 5 before migration and preserved both bots, two allocated hedge positions, all 20 native order journals (including preserved historical records), fills, operations, cycle timing and initialized ETH grid geometry exactly. Read-only native endpoints and the actual grid panel confirmed existing ETH settings remained Arcus 25x cross and Robinhood 2x cross. No margin-setting operation was created. The live ETH grid was already attention due to expired market data before the update, and the hedge was already paused; the release preserved those user/runtime states. Browser form verification checked selected investment/leverage/mode and live computed notional without saving or running a bot.

## Recovering from transient grid quote failures (2026-10-13)

The ETH grid's old stop at 16:44 was retained as attention even after public quotes were healthy. Read-only probes could not reconstruct that historical quote age; the old log contained no quote timestamp. Deterministic regressions exposed the concrete handling bug: a single expired book entered the same permanent attention path as execution uncertainty. They also reproduced a preview race where the account check aged an earlier quote beyond 15 seconds, and the monitor incorrectly labeled an order-free historical stop as unknown orders/inventory. The initial four cases failed in 0.52 seconds with `uv run pytest -q tests/test_grid_quotes.py`.

Quote reads now raise a distinct unavailable condition for stale/future/invalid timestamps and transient transport/rate-limit failures. Grid ticks skip these actions while retaining waiting/holding authority, original cursor and inventory, and fetch a fresh quote on the next tick. Preview fetches price after account checks; the final pre-order check retains the original 15-second/non-future policy. Freshness rejection logs include provider, symbol, age, venue time and local time without credentials. Read retries remain bounded; permanent request failures still stop.

If a pending grid action has no order journal, the transaction can mark it skipped and discard only an unsent initial layout. Existing initialized geometry is preserved. Any order journal prevents this path, including fully confirmed fills awaiting cursor commit; normal original-order reconciliation and explicit resumption still apply. History is retained, not erased or treated as a fill.

Old attention bots are not automatically enabled by the upgrade. Run can explicitly resume an aligned, confirmed grid after account/order/margin and fresh-quote checks; unknown operations and partial targets block it. Historical stop reasons display the record update time and current quote availability instead of implying an unknown order. Record update time is not asserted to be the failure event time because a name edit also changes it. Manual pause remains effective through quote recovery.

All 216 tests, Ruff and mypy passed. Fourteen quote regressions cover initialized and initial outages, delayed account checks, final-quote expiry before signing, transport/timeouts/limit versus permanent errors, readback after lost ACK, notification deduplication, manual pause, future timestamp diagnostics, confirmed fills with interrupted cursor commit and old-attention resumption without automated trading.

The local update preserved the user-resumed ETH grid in holding, the hedge in pause, original grid levels/cursor/quantity, two allocated hedge positions, all 20 existing native order journals, fills, operations, cycle timing and turnover. SQLite was backed up; no trading command or native margin-setting submission was made during verification. The actual browser showed normal ETH monitoring with fresh public quotes and its unchanged next signals.
