# Implementation slices and acceptance

Status: proposed; no slice has been implemented. Scope is Perp Farming Bots, a single-owner self-hosted application with built-in trading strategies. The first delivered strategy is spread hedging; estimates in DESIGN.md cover that strategy and do not include unspecified grid/scalping implementation.

## Slice 1 — Runnable read-only application

Create Python packaging, release dependency locks, NiceGUI strategy catalog and bot pages, SQLite migrations, administrator login, local encrypted connection storage, structured redacted logs and a Docker image. The catalog labels spread hedging as planned for V1 and grid/scalping as future, not available. Validate Lighter SDK native signer import on the advertised Linux architectures. Use a read-only Lighter RH connection for actual public market data.

Acceptance: a clean supported host can start the image; user connects from browser, sees real catalog and live/expired status; restarting preserves settings; no code path can submit a trade in read-only mode. Docker installation is a documented prerequisite, not an existing feature of this repository.

## Slice 2 — Persistent multi-lot paper workflow

Implement explicit bot identities, versioned strategy parameters/state, create/preview/pause/stop/stop-and-close commands and the first spread-hedging module. Keep one-leg and multi-leg execution operation types explicit. Add Decimal quantities, same-direction shared-net lot allocation, account/market locking, account funds reservations, fill uniqueness and operation idempotency. Build a clearly labeled paper adapter with deterministic fault injection, not a mock that masquerades as a real venue.

Acceptance: two bots/lots on the same pair can be independently opened and closed; multiple pairs run concurrently; opposing lot requests on one native account/contract are rejected before dispatch; repeated commands return the same operation. Pause/stop/close are distinct; a stopped bot's remaining inventory stays visible. A single-leg execution lifecycle contract verifies the shared module is not pair-only. Paper results are never shown as official fills or official points.

## Slice 3 — Durable Lighter submission and recovery

Implement explicit RH/Core deployment profiles and the official SDK prepare/sign/persist/send/query sequence. Store native submit identities and validity/nonce data; verify fill history and reduce-only paths. Account namespaces remain separated even if a numeric account index is identical across deployments.

Acceptance: dropped ACK, query unavailable, rejection, partial fill, and restart at every submit/fill transaction point do not produce duplicate replacement orders. A miss remains unknown until native evidence determines the result. Read-only/sandbox tests first; small funded-account tests require explicit user authorization.

## Slice 4 — Existing-library second venue and paired execution

Select one public SDK or CCXT connector with sufficient order recovery evidence. Implement the protected IOC first-leg / actual-fill second-leg workflow and authorized operation-local compensation. Enforce the declared maximum quantity/slippage and show actual target completion. Do not auto-repeat a completed or partially completed entry.

Acceptance: a fault in either leg produces truthful operation progress; closing a single lot never uses close-all; unavailable market metadata and stale books cannot cause submission; unrelated lots remain usable. Verify no implicit builder/referral fees. Completing one native round trip is necessary but does not certify crash recovery.

## Slice 5 — Independent Arcus perpetual adapter

Obtain accessible official perpetual authentication, order, query and fill documentation; implement independently from those public contracts. Do not copy or consult private adapters, fixtures or previous native captures. Verify signing scope, market units, limit/IOC behavior, original-order lookup, fees, WS generation/reconnect behavior and rate limits with new evidence.

Acceptance: the adapter passes the same durable-submit and recovery contracts as Slice 3/4. Failed or unavailable history produces uncertainty, not zero fill. The official spot SDK is not used for perpetual orders. Arcus/RH is an execution test pair only until points eligibility is independently established for the intended usage.

## Slice 6 — Fact-based cost and PnL

Add realized/unrealized PnL, actual fees, account funding events and transparent per-lot allocation quality. Preserve currencies and explicit valuation sources. Account balance changes and unrelated positions do not enter strategy PnL.

Acceptance: aggregate allocated fills/fees reconcile to known source totals; missing fee/FX/funding data cannot create a false complete total; estimated allocations are clearly labeled. Deposits/withdrawals are not profit.

## Slice 7 — Points and actionable notifications

Verify each platform's actual program, eligible activities and official read path. Build low-frequency independent points reads, account/season views, persistent alert deduplication and Telegram delivery. Add actionable pages for unknown orders, residual positions and external account changes.

Acceptance: unreadable, redacted, pending, stale and officially known zero points are distinct; points are not invented from turnover or per-lot allocation. Notification downtime does not block closing. Full host downtime requires an optional independently hosted heartbeat monitor, not a promise from the dead host.

## Slice 8 — Self-hosted beta release

Provide pinned non-root images, Compose instructions, first-start connection wizard, encrypted backup/export, upgrade/restore instructions, screenshots, public support matrix, security reporting instructions, dependency license inventory and notices. Recovery operations remain visible across upgrades.

Acceptance: test from a clean supported machine; admin actions are authenticated on HTTP/UI/real-time transport; secrets never enter exports/logs/browser persistent storage; restore warns against concurrent old/new instances and resumes original submissions before new trading. Publish only genuinely validated venues and container architectures.

## Slice 9 — Built-in grid strategy

Specify direction, price range, grid count/spacing, inventory and order budget, out-of-range behavior and pause/stop behavior before implementation. Reuse public connectors, submit recovery, Decimal accounting, order ownership, PnL and notifications; implement only grid level state, order scheduling and fill-driven replacement in the grid module.

Acceptance: partial fills, cancel/fill races and restart do not duplicate grid orders; stopping cancels only this bot's orders and retains visible allocated inventory; stop-and-close drains known owned orders before closing final inventory. Initially reserve the native account/contract exclusively for this bot until cross-strategy net ownership is verified. No implicit portfolio stop-loss or margin adjustment.

## Slice 10 — Built-in scalping strategy

Define the exact entry/exit signal, market/order type, single-trade amount, cumulative budget, cooldown and termination conditions. “Scalping” alone is not an executable specification. Reuse the same runtime; keep its signal/round-trip state in a strategy-owned versioned module.

Acceptance: cost/fees and real fills are measured; delayed or unknown orders cannot start a duplicate round trip; explicit rule-based exits are documented user-selected behavior; an aborted strategy is not misreported as a flat account. Independently validate order-rate constraints and strategy sharing before live release.

## Expansion after beta

Add other public-library venues individually through the same connector contracts. Inverse/complex-unit instruments, opposing same-account positions, desktop installers, sophisticated order routing and optional portfolio risk management are independent milestones; do not add compatibility fields or guessed behavior to imply support. Reevaluate complete public strategy frameworks if a later strategy's actual requirements make them cheaper than the small current runtime; preserve verified licenses and user-visible referral/fee behavior.

## Release-critical failure matrix

| Failure | Required behavior |
| --- | --- |
| Duplicate click / browser reconnect | Same durable operation, no duplicate trade |
| SDK send accepted but response lost | Query original identity; no blind replacement |
| Process dies before/after each journal commit | Resume durable state and facts |
| First leg partial, peer step cannot execute | Explicit remaining exposure and authorized compensation |
| Peer order uncertain | Resolve peer before additional hedging/unwind |
| Two lots share one native net | Close allocated quantity only; other lot unchanged |
| External trade / ADL changes net | Preserve evidence and attribution gap; no guessed overwrite |
| Fee/funding/points data missing | Explicit incomplete/unknown status |
| SQLite write failure / disk full | No unjournaled new send; preserve pending state |
| Notification/points/UI worker failure | Trading operation lifecycle continues independently |
| Restored copied DB while old host runs | Refuse advertised dual-active behavior; operator stops old instance |
