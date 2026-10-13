# Implementation scope

Product: Perp Farming Bots, independent and self-hosted. Priorities are the main program and novice-friendly flows. Security/login design is deferred. No private trading project code or artifacts may be reused.

## Delivered native execution path

The browser connects actual Arcus, Lighter Core and Lighter Robinhood account instances. Credentials are checked before an instance is saved. Bindings use native account identity; another API key for the same native account cannot create an independent account.

A spread bot has its own identity, two account bindings, symbol, threshold, target notional, price bound and lifecycle. Multiple bots can run across different venues or different accounts on one venue. BTC/ETH/SOL are the initial scope; unverified asset units are rejected.

The execution path reads both real books and their precisions, checks native inventory against owned allocations, journals the signed first-leg request, sends once, then queries the original order. The second leg uses the actual filled quantity that its market precision permits. An unmatched remainder stays visible with an alert. The runtime adds no unrequested compensation or automatic risk trades.

Closing checks original order uncertainty and actual native inventory, submits reduce-only for the selected bot's quantity and records confirmed fills. Partial close retains the remainder. The optional scheduled strategy uses the same close path, advances its durable cycle only after complete confirmation, persists a bounded random wait and checks the original spread before the next entry. Pause preserves inventory and disarms the timer; run resumes held inventory with a fresh interval. Manual close ends the loop. The three primary actions remain run, pause and close. Schema 4 explicitly migrates legacy states and adds cycle/points history tables without trading.

Restart and synchronization query original identities without reissuing requests or automatically submitting a missed second leg. Recent-history lookup can remain unknown when evidence has aged out; this is explicit, not assumed rejection or zero fill.

Order confirmation retries transient native reads within the existing bounded polling loop rather than aborting at the first query exception. Invalid identity remains a permanent stop. Query failure causes are retained in operation history; synchronization updates the current exposure description without erasing the original diagnostic. The UI retains per-bot elements and updates values/visibility in place; creation and deletion alone change the card list. Alert polling preserves notification-setting drafts.

Acceptance covered by current tests: per-bot close ownership, same-venue multiple accounts, creation idempotency, original-order lookup after lost ACK, first/peer/close partial fills, no blind repeat, stale quotes and external-inventory blocking. Production credentials and real funded orders have not been used for acceptance yet.

The browser/API supports bot parameter editing and confirmed deletion. Entry bindings stay fixed after execution; confirmed holding bots can adjust close slippage. Editing entry parameters stops condition monitoring until explicit restart. Deletion is blocked by owned inventory or unresolved journals and retains historical rows. Both create/edit and account onboarding validate names before submission and reuse a single form per page.

Lighter zero fees are verified against authenticated native trades for the exact account, client identity and order. Complete cumulative size/notional evidence is required. Native omitted zero fee fields are interpreted according to the official Trade JSON contract. Fee-read failure keeps fees unknown while preserving confirmed quantity and price. Later evidence may enrich only a previously unknown fee, without replaying inventory or altering terminal fill evidence.

Funding cards read Arcus market metadata and short, read-only Lighter market_stats subscriptions, caching for 30 seconds. Both display native hourly estimates separately from last settlement rates, with explicit unavailability. Funding is still excluded from actual bot PnL until payment attribution is implemented.

## Next acceptance step

Connect user-owned accounts through the application and verify private identity, balance and position reads. Then perform an explicitly user-controlled small entry/close on each profile, compare native order and fill records, and verify fees, reduce-only and native precision. Public reads and local fixtures are insufficient evidence of funded execution.

## Remaining modules

- Long-range paginated native history and WebSocket reconciliation.
- Lighter nonzero fee monetary accounting, actual funding payment attribution and official points.
- Additional exchange account/execution adapters.
- Resting-order grid and scalping: define rules and active-order/cancellation semantics before implementing.
- Security/access design after the main flows, without preselecting passwords or Basic Auth.
- Release packaging, upgrades and additional container architectures.

Keep ordinary transactions and one application process. Do not pursue latency tuning, distributed infrastructure or exhaustive reliability work during this stage.

## Price-triggered grid (2026-10-13)

`grid.py` adds a single-account long/short/neutral planner and durable cursor. `hummingbot_grid.py` adapts the pinned public Distributions.linear with attribution; the full Hummingbot executor is a reference only. `grid_ui.py` supplies direction, range, grid count, investment-margin budget, leverage and margin mode with validation on Save. `GridBotCard` reuses trading metrics and controls but displays one actual net inventory.

Grid orders reuse `_execute`, the official Lighter signer, Arcus signing, original-identity lookup, terminal fill accounting and reduce-only close. Grid additions support weighted inventory accumulation; hedge duplicate-entry rejection remains intact. Account/symbol reservations block cross-strategy mixing. Schema 5 only adds grid state/action tables to schema 4. Full/unknown/partial evidence controls cursor progression; recovered complete evidence pauses rather than trading again. Details: [GRID.md](GRID.md).

Native margin settings use `native_margin.py` for explicit venue units and `margin.py` for journal-before-send configuration and fresh readback. Schema 6 adds encrypted setting operations and migrates legacy grid capital to an explicit notional variant. New margin grids size by investment × leverage; Run applies settings only on flat inventory, uncertain results block strategy activation, and synchronization confirms without resending or auto-resuming. Grid cards show actual native settings separately from selected strategy budget. Protocol sources: [margin.md](research/margin.md).
