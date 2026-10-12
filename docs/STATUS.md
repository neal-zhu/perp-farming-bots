# MVP implementation status

Validated 2026-10-12. The application is an independent, runnable **paper-only MVP**, not a certified real-money trading bot.

## Delivered

- Python/NiceGUI browser application and authenticated HTTP/real-time transports.
- Multiple explicit account instances on the same venue; bots bind instance IDs.
- Built-in strategy catalog, with spread hedging enabled for simulation and grid/scalping clearly unavailable.
- Multiple bots, creation idempotency, start/pause/resume/stop and bot-specific paper close.
- Decimal paper quantities, fees, account-capacity accounting and per-bot inventory allocation.
- Persistent SQLite bots, positions, fills, operation history and station alerts.
- Real/public quote reader implementations for the official Lighter Core/RH SDK and Hyperliquid/Binance CCXT.
- Explicit virtual demo sources, per-leg provenance and no virtual fallback after public-data failure.
- Paper realized/unrealized PnL with explicit missing quotes, funding and points state.
- Optional locally encrypted Telegram configuration and user-triggered connection test.
- Frozen dependency lock, non-root Docker image, Compose and GitHub CI.

## Verification

- Ruff and mypy passed.
- 18 tests passed, including same-venue separate accounts, independent multi-bot close, capacity, idempotency, stale data, restart, private API flow, HTTP/WS origin checks and encryption.
- Browser flow passed: create demo accounts -> preview/save bot -> start -> holding -> close -> fill history. No browser page errors were observed.
- Linux ARM64 Docker build and actual HTTP paper open/close flow passed.
- Official native signer library loaded without signing transactions, on development macOS ARM64 and the Linux ARM64 container.
- CI on implementation commit `6fe5224` passed: [run](https://github.com/neal-zhu/perp-farming-bots/actions/runs/38209947385).

The existing FastAPI/Starlette test client emits a dependency deprecation warning; it did not fail the suite. No benchmark, distributed failover or exhaustive chaos suite was added.

## Explicit remaining work

- Private/native exchange account reads and credential onboarding.
- Real order preparation/submission/status recovery and partial-fill handling.
- Arcus public/private perpetual adapter.
- Official points programs/read paths and funding collection/allocation.
- Grid/scalping rules and implementations.
- Other container architectures and desktop installers.

This environment's public quote probes failed with TLS/network errors; those venues are implemented read paths but not connectivity-certified here. Paper quantities and fees, virtual quotes, face-value simulated USD conversions and locally atomic paper fills must not be presented as native execution evidence. No live trades or private exchange credentials were used.

The private GitHub repository is [neal-zhu/perp-farming-bots](https://github.com/neal-zhu/perp-farming-bots). No code or artifacts from a private trading project were reused.
