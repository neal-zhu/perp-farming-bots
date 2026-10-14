# Bot and account model

A bot is an independent strategy instance: its ID, typed parameters, account bindings, lifecycle, allocated inventory, execution operations, orders, fills, trading PnL and alerts. Points belong to an account scope, not automatically to a bot.

## Identity and ownership

An account instance is a native trading account rather than an exchange label. Its provider and native identity are verified before storage. Multiple accounts on one venue are allowed; multiple keys for one native account do not create independent accounts. Native identity rules are in [exchange scope](exchanges.md).

A spread bot binds two different account instances. A grid binds one account. A grid reserves that account/symbol exclusively; it cannot share inventory with another bot or a manual position. Compatible same-direction spread bots can share a native account/symbol, with allocations tracked separately.

The exchange may net positions across a symbol. Bot inventory is derived from confirmed fills and must reconcile with that native net inventory. Close uses only the selected bot's allocation with reduce-only, never an account-wide close-all.

| Model | Meaning |
| --- | --- |
| `Connection` | Verified native identity; private credentials are stored separately and encrypted |
| `Bot` | Configuration, strategy ID, state and reason; `request_id` makes creation idempotent |
| `Position` | Confirmed quantity, side and entry price allocated to one bot |
| `OrderIntent` | Account/symbol, side, quantity, limit price, reduce-only and stable client ID |
| `OrderResult` | Explicit terminal or unknown result, quantity, average price, fee and native ID |
| Operation | A bot-authorized open, close, reopen or grid action, with status and recovery evidence |
| Cycle | Spread round, original entry operation, reopen time and persisted random wait |
| Grid state/action | Persisted levels, quantity per grid, cursor, zero-inventory origin and pending target |
| Margin change | Encrypted prepared native settings and confirmation evidence |

Definitions: [models.py](../src/perp_farming_bots/models.py). Tables and transactional rules: [store.py](../src/perp_farming_bots/store.py).

## Lifecycle

| Internal state | Meaning |
| --- | --- |
| `ready` | Configuration saved; waiting for an explicit Run |
| `waiting` | Enabled and waiting for entry conditions or grid initialization |
| `holding` | Confirmed strategy state; may retain inventory or monitor an initialized flat grid |
| `paused` | New strategy actions disabled; allocated inventory retained |
| `closed` | Allocated inventory closed; an explicit Run may begin another cycle/layout |
| `attention` | Execution/inventory evidence requires reconciliation or operator review |

Run, Pause and Close are the user trading controls. Internal `sync` queries original evidence. Synchronization of an interrupted successful operation does not silently re-enable a paused strategy. No separate stop state is exposed.

Saving a configuration sends no order. Changing trading parameters can require another Run. Historical orders lock account/symbol meanings; flat paused/closed grids may change their geometry and capital only when no unresolved operation remains. The server enforces editability independently of button state.

Deleting an eligible bot removes its configuration and grid layout but retains order, fill and operation history. Owned inventory or unresolved operations block deletion. [store.py](../src/perp_farming_bots/store.py) is authoritative for field-level editability.

## Displayed accounting

Trading PnL uses confirmed inventory and fills, deducts known fees and excludes actual funding payments. Unknown fees can make net PnL unknown. Turnover sums each confirmed fill's quantity × average price across all bot cycles; fee enrichment or repeated synchronization does not count the fill again.

Funding is a market forecast with a source and timestamp, not an attributed payment. Account points retain their native scope and missing samples. Details: [hedging](hedging.md), [grid](GRID.md), [points protocol](research/points.md).
