# Perp Farming Bots

[简体中文](README.zh-CN.md) · [User guide](docs/guide.zh-CN.md) · [Documentation](docs/README.md)

A self-hosted dashboard for perpetual trading bots. Connect your own exchange accounts, configure a built-in strategy, and track each bot's positions, fills, trading PnL and turnover. The web interface is currently in Simplified Chinese.

The application supports **cross-account spread hedging** and **long, short and neutral grids**. Multiple bots and multiple accounts on the same exchange are supported. Account points are sampled separately from bot trading results.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git. Python 3.12 is selected by the repository configuration.

```bash
git clone https://github.com/neal-zhu/perp-farming-bots.git
cd perp-farming-bots
uv sync --frozen
uv run perp-farming-bots
```

Open **http://127.0.0.1:8080**. Connect an account, create a bot and click **运行** (Run). Saving a configuration does not start trading.

Docker Compose is an alternative:

```bash
docker compose up --build -d
```

The default setup is local only. **The UI and API have no authentication**; keep the localhost binding. Details, configuration, backups and server access: [Operations](docs/operations.md).

## Available integrations

| Venue | Trading | Account points |
| --- | --- | --- |
| Arcus | Native perpetual account and IOC execution | Not integrated |
| Lighter Core | Official native signing SDK and IOC execution | Not integrated |
| Lighter Robinhood | Separate native deployment and signing domain | Live total and historical chart |
| Entropy | Hyperliquid main and Entropy `io:*` perpetual markets | Not integrated |

Ticker lists come from each selected venue’s active perpetual market catalog and are searchable. Each hedge leg selects its own ticker; the application performs no cross-venue asset-equivalence validation. Entropy requires a main trading account and a registered API agent; unified/portfolio margin, subaccounts and vaults are excluded. See [exchange setup and verified scope](docs/exchanges.md).

## How bots work

- **Spread hedging:** bind two different account instances and select each leg’s ticker, spread threshold and target USD amount per leg. Quantities use each market’s own price and precision; the second leg follows the first leg’s confirmed fill notional. Optional timed reopening closes the owned pair, waits a bounded random interval and checks the spread again.
- **Grid:** bind one account, choose long/short/neutral, a fixed price range, grid count, investment margin, leverage and margin mode. The program watches prices and sends an IOC order when the next line is reached. Grid lines are conditional plans; orders are not placed on the exchange in advance.
- **Run / Pause / Close:** Run enables or resumes the selected strategy; Pause keeps positions; Close handles only that bot's allocated inventory. A confirmed closed bot can run again.

Signed orders are journaled before sending. Unknown outcomes are queried by the original order identity and are never blindly resent. Temporary reads retry; continuous failure for five minutes pauses the affected active strategy. The application adds no automatic stop-loss, compensating hedge or margin top-up outside the selected strategy's rules.

Trading PnL deducts confirmed fees and excludes actual funding payments. Funding forecasts are shown separately. Missing fees, points or execution evidence stay explicitly unknown. Points displays do not certify reward eligibility. Automated tests validate protocol handling and strategy logic; funded acceptance is venue-specific and is not certified by this project.

![Implemented strategy library in the web interface](docs/assets/strategies.png)

## Development and agent entry point

```bash
uv sync --frozen
make check
make test
```

Start with [AGENTS.md](AGENTS.md), then [CONTRIBUTING.md](CONTRIBUTING.md) and the [code and test map](docs/development.md). Documentation links are checked by `make docs-check` and CI. [Architecture](docs/architecture.md) describes the actual execution and persistence boundaries; [API reference](docs/api.md) describes the local endpoints.

## License and provenance

Application code is Apache-2.0. Public dependency licenses, SDK pins and the attributed Hummingbot grid geometry adaptation are recorded in [UPSTREAMS.md](UPSTREAMS.md). No private trading project's implementation, credentials or runtime data are included.
