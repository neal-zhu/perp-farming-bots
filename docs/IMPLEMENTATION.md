# Implementation slices and acceptance

Status: proposed; no slice has been implemented. Scope is a single-owner self-hosted application, not a hosted multi-tenant service. Estimates in DESIGN.md are conditional planning estimates.

## Slice 1 — Runnable read-only application

Create Python packaging, release dependency locks, NiceGUI pages, SQLite migrations, administrator login, local encrypted connection storage, structured redacted logs and a Docker image. Validate Lighter SDK native signer import on the advertised Linux architectures. Use a read-only Lighter RH connection for actual public market data.

Acceptance: a clean supported host can start the image; user connects from browser, sees real catalog and live/expired status; restarting preserves settings; no code path can submit a trade in read-only mode. Docker installation is a documented prerequisite, not an existing feature of this repository.

## Slice 2 — Persistent multi-lot paper workflow

Implement create/preview/cancel/close commands, Decimal quantities, same-direction shared-net lot allocation, account/market locking, account funds reservations, fill uniqueness and operation idempotency. Build a clearly labeled paper adapter with deterministic fault injection, not a mock that masquerades as a real venue.

Acceptance: two lots on the same pair can be independently opened and closed; multiple pairs run concurrently; opposing lot requests on one native account/contract are rejected before dispatch; repeated commands return the same operation. Paper results are never shown as official fills or official points.

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

## Expansion after beta

Add other public-library venues individually through the same connector contracts. Inverse/complex-unit instruments, opposing same-account positions, desktop installers, sophisticated order routing and automated risk strategies are independent milestones; do not add compatibility fields or guessed behavior to imply support.

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
