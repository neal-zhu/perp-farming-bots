# Framework research for Perp Hedge Kit

Verified 2026-10-12 against public upstream repositories and first-party documentation. This research used no private trading repository, credentials, or live orders. Connector support below means source-level verification, not a successful authenticated trading test.

## Recommendation

Use official venue SDKs/HTTP APIs behind a small independently implemented Python coordinator, a self-hosted UI, and a durable SQLite journal. A NiceGUI/FastAPI UI is a reasonable deployment choice for the proposed single-service product; this is an architectural judgment, not a capability supplied by the trading frameworks.

For the Arcus + Lighter Robinhood pilot, a whole Hummingbot or Nautilus stack does not remove the Arcus integration. The official Lighter Python SDK already has explicit Robinhood endpoint and signing-chain profiles. CCXT is attractive as an optional adapter for subsequent supported venues, rather than the foundation of pair ownership and recovery. Hummingbot is the strongest alternative if its full bot-management product is desired. Nautilus is strongest if the product grows into a broader event-driven trading engine. These rankings are judgments based on the verified evidence below.

“No active risk management” should mean no strategy-driven liquidation, stop-loss, take-profit, automatic deleveraging, or rebalancing. It still requires durable order intents, partial-fill accounting, restart reconciliation, freshness checks, and alerts when a leg is unresolved. A timeout must remain an unknown order outcome until verified; automatically resending it can duplicate exposure. Each venue must explicitly verify the order identity and reduce-only close semantics before enabling live execution.

## Pinned public sources and licenses

| Component | Public repository / inspected commit | Commit date (UTC) | Verified license |
| --- | --- | --- | --- |
| Hummingbot core | [hummingbot/hummingbot, `9af100d`](https://github.com/hummingbot/hummingbot/tree/9af100d6822da7d2d0291a906c730ef172284ee2) | 2026-09-22 | [Apache-2.0](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/LICENSE) |
| Hummingbot API | [hummingbot/hummingbot-api, `d276034`](https://github.com/hummingbot/hummingbot-api/tree/d276034aee978d826bf05afcc2197eb1360c4a6a) | 2026-09-22 | [MIT](https://github.com/hummingbot/hummingbot-api/blob/d276034aee978d826bf05afcc2197eb1360c4a6a/LICENSE) |
| Hummingbot Dashboard | [hummingbot/dashboard, `ee42595`](https://github.com/hummingbot/dashboard/tree/ee42595bec85518eda0b9fe1a56046d09a3e36c6) | 2025-10-27 | [Apache-2.0](https://github.com/hummingbot/dashboard/blob/ee42595bec85518eda0b9fe1a56046d09a3e36c6/LICENSE) |
| CCXT, including Pro | [ccxt/ccxt, `4004c1a`](https://github.com/ccxt/ccxt/tree/4004c1a04ab43a4ed7b8e14944846a4f64e9fefd) | 2026-10-11 | [MIT](https://github.com/ccxt/ccxt/blob/4004c1a04ab43a4ed7b8e14944846a4f64e9fefd/LICENSE.txt) |
| NautilusTrader | [nautechsystems/nautilus_trader, develop `dde463a`](https://github.com/nautechsystems/nautilus_trader/tree/dde463a1692320d42cc6754bebbdd1fba103e4c0) | 2026-10-12 | [LGPL-3.0](https://github.com/nautechsystems/nautilus_trader/blob/dde463a1692320d42cc6754bebbdd1fba103e4c0/LICENSE) |
| Freqtrade, additional mature alternative | [freqtrade/freqtrade, develop `19e077f`](https://github.com/freqtrade/freqtrade/tree/19e077f703869b6baec0f7024d9520e85943ed38) | 2026-10-12 | [GPL-3.0](https://github.com/freqtrade/freqtrade/blob/19e077f703869b6baec0f7024d9520e85943ed38/LICENSE) |
| Official Lighter Python SDK | [elliottech/lighter-python, `04bee9b`](https://github.com/elliottech/lighter-python/tree/04bee9ba9811b87ef1cccc568e7f590b5fe649bb) | 2026-09-30 | [Apache-2.0](https://github.com/elliottech/lighter-python/blob/04bee9ba9811b87ef1cccc568e7f590b5fe649bb/LICENSE) |

Retain upstream license and notice files for redistributed dependencies or copied public code. Copyleft frameworks have different redistribution obligations from permissively licensed SDKs; do not silently treat the licenses as interchangeable. The recommendation uses dependencies rather than transplanting framework implementations.

## Exact pilot support

Lighter Robinhood is a separate Lighter instance with separate contracts, sequencer, blockspace, and liquidity. Its official API base is `https://api.rh.lighter.xyz`. Lighter Core, Robinhood Crypto Trading API, and Lighter Robinhood must be distinct venue identities. [Robinhood Chain documentation](https://docs.robinhood.com/chain/lighter-domains/)

| Candidate | Lighter Core perpetuals | Lighter Robinhood perpetuals | Arcus perpetuals |
| --- | --- | --- | --- |
| Hummingbot core/API/Dashboard | Verified connector | No explicit support verified at pin; connector declares only Core mainnet/testnet | No verified connector |
| CCXT Python async / Pro | Verified REST and WebSocket connector | No explicit RH domain verified at pin; custom endpoint/chain settings would require independent validation | No verified connector |
| NautilusTrader current source | Verified adapter | Explicitly supported in current develop and master source; packaged stable support unverified | No verified connector |
| Freqtrade | Not on its advertised supported futures list | Not verified | Not verified |
| Official Lighter Python SDK | Explicit profile | Explicit RH profile, REST/WS and chain ID `466324` | Outside SDK scope |

Hummingbot's [`lighter_perpetual_constants.py`](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/connector/derivative/lighter_perpetual/lighter_perpetual_constants.py) declares `mainnet.zklighter.elliot.ai` and its testnet; its [config map](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/connector/derivative/lighter_perpetual/lighter_perpetual_utils.py) lists only the testnet as another domain. That is not RH verification.

CCXT's [Python async adapter](https://github.com/ccxt/ccxt/blob/4004c1a04ab43a4ed7b8e14944846a4f64e9fefd/python/ccxt/async_support/lighter.py) has `swap=True`, position/order methods, Core URLs, default signing chain `304`, and a sandbox switch to `300`. Endpoint and chain overrides are possible configuration inputs, but cannot establish RH support by themselves. At this pin it also defaults `builderFee=True` with integrator attribution/fee parameters; inspect their applicability and costs before reuse. Do not assume normalized methods provide venue points.

Nautilus's [deployment selector](https://github.com/nautechsystems/nautilus_trader/blob/dde463a1692320d42cc6754bebbdd1fba103e4c0/crates/adapters/lighter/src/common/deployment.rs) explicitly defines RH mainnet/testnet URLs, signing-chain selection, `USDG`, and a separate venue. The same file exists with RH support on [master `7b766f8`, 2026-10-04](https://github.com/nautechsystems/nautilus_trader/blob/7b766f8825b2539c5b2ac1375e9d97b41c509edb/crates/adapters/lighter/src/common/deployment.rs). The [latest GitHub release `v1.231.0`](https://github.com/nautechsystems/nautilus_trader/releases/tag/v1.231.0), published 2026-08-02, has no such file and its [Lighter README](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/crates/adapters/lighter/README.md) does not claim RH. Therefore current-source support must not be advertised as verified support in that release.

The official SDK's [endpoint profiles](https://github.com/elliottech/lighter-python/blob/04bee9ba9811b87ef1cccc568e7f590b5fe649bb/lighter/endpoint_profiles.py) and [signer client](https://github.com/elliottech/lighter-python/blob/04bee9ba9811b87ef1cccc568e7f590b5fe649bb/lighter/signer_client.py) explicitly handle RH. This is stronger pilot evidence than a generic framework connector branded “Lighter.”

No Arcus-named connector appeared in the complete, non-truncated pinned repository trees for [Hummingbot](https://api.github.com/repos/hummingbot/hummingbot/git/trees/9af100d6822da7d2d0291a906c730ef172284ee2?recursive=1), [CCXT](https://api.github.com/repos/ccxt/ccxt/git/trees/4004c1a04ab43a4ed7b8e14944846a4f64e9fefd?recursive=1), or [Nautilus](https://api.github.com/repos/nautechsystems/nautilus_trader/git/trees/dde463a1692320d42cc6754bebbdd1fba103e4c0?recursive=1). Treat Arcus as a new adapter until its native perpetual market, signer, and account semantics are independently verified. A dYdX connector or a spot SDK is not proof of Arcus perp support.

## Product fit and recovery burden

**Hummingbot:** Provides mature connector and order-tracking infrastructure, V2 controllers/executors, credential handling, and orchestration. Its stock [V2 arbitrage executor](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/strategy_v2/executors/arbitrage_executor/arbitrage_executor.py) submits one buy and one sell and stops once both fill. It is not a complete persistent hedge-position product with later user-directed pair closure. Pair ownership, independent leg reconciliation, points, and the requested UI remain custom work. The [API README](https://github.com/hummingbot/hummingbot-api/blob/d276034aee978d826bf05afcc2197eb1360c4a6a/README.md) offers balances, positions, P&L and bot management. Its [Compose file](https://github.com/hummingbot/hummingbot-api/blob/d276034aee978d826bf05afcc2197eb1360c4a6a/docker-compose.yml) runs API, PostgreSQL and EMQX and mounts the Docker socket; bot containers add more services. Dashboard adds its own container, and its [README](https://github.com/hummingbot/dashboard/blob/ee42595bec85518eda0b9fe1a56046d09a3e36c6/README.md) says authentication is disabled by default. This is a broader deployment than the pilot needs.

**CCXT:** The lightest general connector library, with Python async REST and `ccxt.pro` WebSocket APIs. **Pro is now free**, not a separate paid dependency; the [official Pro manual](https://docs.ccxt.com/docs/pro-manual) says so. It handles subscription caches, reconnection and backoff, but those in-memory caches are not a durable pair journal. The app must implement persistence, account isolation, fill deduplication, retries after verified outcomes, and startup reconciliation. The pinned [Lighter Pro adapter](https://github.com/ccxt/ccxt/blob/4004c1a04ab43a4ed7b8e14944846a4f64e9fefd/python/ccxt/pro/lighter.py) supports books, balances, orders and own-trades streams, but declares `watchPositions=False`; polling or a native account stream is still necessary. Good extension layer, conditional pilot fit.

**NautilusTrader:** The current [Lighter integration guide](https://github.com/nautechsystems/nautilus_trader/blob/dde463a1692320d42cc6754bebbdd1fba103e4c0/docs/integrations/lighter.md) documents order reconciliation, nonce recovery, pending submission outcomes and reconnect behavior. This is the strongest supplied execution-recovery machinery of the compared candidates. Its [adapter README](https://github.com/nautechsystems/nautilus_trader/blob/dde463a1692320d42cc6754bebbdd1fba103e4c0/crates/adapters/lighter/README.md) states that Python bindings are narrow: configuration, enums, factories and revocation; clients are consumed through Rust traits. It also says RH mainnet startup applies the account-level `NAUTILUS` referral code, with failures logged without blocking trading. This behavior must be an explicit product choice, especially for a points-oriented tool. A Rust engine, Python extension, strategy model and new Arcus adapter add integration burden without supplying the requested self-host UI.

**Freqtrade:** A mature bot/UI/Telegram alternative, but its [supported futures list](https://github.com/freqtrade/freqtrade/blob/19e077f703869b6baec0f7024d9520e85943ed38/README.md) does not include Lighter or Arcus. Its [leverage guide](https://github.com/freqtrade/freqtrade/blob/19e077f703869b6baec0f7024d9520e85943ed38/docs/leverage.md) warns that it assumes exclusive use of the account. Its single-exchange bot model would need a substantial new paired coordinator; inheriting CCXT availability is not Freqtrade connector verification. No advantage for this pilot.

## What the chosen coordinator still owns

- Explicit native market mapping and product identity for both legs, including size units, precision, settlement currency and verified close behavior.
- Multiple logical hedge positions even when a venue nets all fills for a symbol into one account position; closing one logical hedge must not unintentionally close another.
- An entry intent with two leg intents, stable client order identities, actual fills and fees, and durable state transitions; unresolved legs block fresh entries and generate alerts.
- Restart and reconnect reconciliation against venue order/fill/account truth before execution resumes.
- User-requested closes and attribution of actual close fills; no automatic risk trades.
- Separate realized P&L, unrealized P&L, fees, funding and points with source timestamps. Missing or unavailable fields remain unknown, and points are venue-specific rather than inferred from volume.

The pilot is ready for live trading only after each adapter passes authenticated venue validation for order status, partial fills, timeout recovery and reduce-only closes. This research did not perform those tests.
