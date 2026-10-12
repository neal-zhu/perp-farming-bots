# Implementation scope

Product: Perp Farming Bots, independent and self-hosted. Priorities are the main program and novice-friendly flows. Security/login design is deferred. No private trading project code or artifacts may be reused.

## Delivered native execution path

The browser connects actual Arcus, Lighter Core and Lighter Robinhood account instances. Credentials are checked before an instance is saved. Bindings use native account identity; another API key for the same native account cannot create an independent account.

A spread bot has its own identity, two account bindings, symbol, threshold, target notional, price bound and lifecycle. Multiple bots can run across different venues or different accounts on one venue. BTC/ETH/SOL are the initial scope; unverified asset units are rejected.

The execution path reads both real books and their precisions, checks native inventory against owned allocations, journals the signed first-leg request, sends once, then queries the original order. The second leg uses the actual filled quantity that its market precision permits. An unmatched remainder stays visible with an alert. The runtime adds no unrequested compensation or automatic risk trades.

Closing is a separate user action. It checks original order uncertainty and actual native inventory, submits reduce-only for the selected bot's quantity and records actual confirmed fills. Partial close retains the remainder. Pause and stop preserve inventory.

Restart and synchronization query original identities without reissuing requests or automatically submitting a missed second leg. Recent-history lookup can remain unknown when evidence has aged out; this is explicit, not assumed rejection or zero fill.

Order confirmation retries transient native reads within the existing bounded polling loop rather than aborting at the first query exception. Invalid identity remains a permanent stop. Query failure causes are retained in operation history; synchronization updates the current exposure description without erasing the original diagnostic. The UI retains per-bot elements and updates values/visibility in place; creation and deletion alone change the card list. Alert polling preserves notification-setting drafts.

Acceptance covered by current tests: per-bot close ownership, same-venue multiple accounts, creation idempotency, original-order lookup after lost ACK, first/peer/close partial fills, no blind repeat, stale quotes and external-inventory blocking. Production credentials and real funded orders have not been used for acceptance yet.

The browser/API supports bot parameter editing and confirmed deletion. Entry bindings stay fixed after execution; confirmed holding bots can adjust close slippage. Editing entry parameters stops condition monitoring until explicit restart. Deletion is blocked by owned inventory or unresolved journals and retains historical rows. Both create/edit and account onboarding validate names before submission and reuse a single form per page.

Funding cards read Arcus market metadata and short, read-only Lighter market_stats subscriptions, caching for 30 seconds. Both display native hourly estimates separately from last settlement rates, with explicit unavailability. Funding is still excluded from actual bot PnL until payment attribution is implemented.

## Next acceptance step

Connect user-owned accounts through the application and verify private identity, balance and position reads. Then perform an explicitly user-controlled small entry/close on each profile, compare native order and fill records, and verify fees, reduce-only and native precision. Public reads and local fixtures are insufficient evidence of funded execution.

## Remaining modules

- Long-range paginated native history and WebSocket reconciliation.
- Lighter trade fee collection, actual funding payment attribution and official points.
- Additional exchange account/execution adapters.
- Grid/scalping: define their actual rules before implementing.
- Security/access design after the main flows, without preselecting passwords or Basic Auth.
- Release packaging, upgrades and additional container architectures.

Keep ordinary transactions and one application process. Do not pursue latency tuning, distributed infrastructure or exhaustive reliability work during this stage.
