# Repository instructions

## Independent implementation

- Do not copy, import, reference as a dependency, or transplant code, tests, fixtures, configuration, or internal documentation from the hedge-arb repository or other private trading projects.
- Implement from this repository’s public specifications and independently verified upstream documentation.
- Reuse public dependencies only after verifying their licenses, supported venue domains, and recovery behavior. Record provenance and required notices.

## Explicit truth

- Unknown order, fill, fee, balance, funding, or points states must remain explicit. Never substitute a zero or a guessed success.
- Do not add compatibility shims, silent fallback fields, or duplicate representations that conceal correctness problems.

## Product and strategy scope

- The product is Perp Farming Bots: a self-hosted application with built-in perpetual trading strategies. Hedging is the first strategy, not the product identity or the shared runtime's data model.
- Model bot instances, strategy-owned state, allocated inventory, orders and execution operations explicitly. Shared execution must support one or multiple legs without making every action a paired hedge.
- Future grid and scalping rules require explicit product specifications; do not invent or enable them because their names appear in documentation.
- User-facing trading actions are run, pause and close. Run also resumes a paused bot; pause preserves inventory; close handles only allocated inventory. Do not reintroduce a separate bot stop action. No account-wide close-all to close one bot.
- Bind bots to connection/account instance IDs, not exchange names. Multiple accounts on one venue may form a pair; an API-key change is not a new native account.

## Delivery priority

- Prioritize a working product and simple implementation. Avoid premature performance tuning, complex distributed infrastructure, or exhaustive reliability mechanisms.
- Keep essential correctness: explicit unknowns, account/strategy ownership, accurate execution labels, and no unjournaled real orders. Fast delivery is not permission to present simulated or unverified behavior as live execution.

## Trading authority

- No live trades, production credentials, automatic risk actions, or upstream service messages without direct user authorization.
- Preserve user-selected strategy authority, durable recovery, and account-scoped isolation. Strategy entries/exits must be declared in the selected strategy; the shared runtime must not add automatic portfolio risk trading.
