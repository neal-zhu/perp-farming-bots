# Development and agent map

Read [AGENTS.md](../AGENTS.md) first. The application currently supports two strategies and four account adapters. [Architecture](architecture.md) and [exchange scope](exchanges.md) describe the actual boundaries.

## Commands

From the repository root:

```bash
uv sync --frozen
make check
make test
make docs-check
```

`make check` runs Ruff, mypy and documentation link checking. `make test` runs pytest with isolated venue doubles. Run one focused file during implementation, for example:

```bash
uv run pytest tests/test_read_outages.py -q
```

For a UI-only development instance, use an empty directory and a separate port:

```bash
PFB_DATA_DIR=/tmp/pfb-dev PFB_PORT=8090 uv run perp-farming-bots
```

Do not use an existing data directory or account keys as test fixtures. Do not start a background Runtime against a funded database to inspect code. Connecting a real account or clicking a trading command is not routine verification.

## Find the change seam

| Change | Implementation | Focused tests |
| --- | --- | --- |
| Parameters, strategy catalog or public input | [models.py](../src/perp_farming_bots/models.py), [api.py](../src/perp_farming_bots/api.py) | [test_api.py](../tests/test_api.py), [test_grid.py](../tests/test_grid.py) |
| Account form validation | [ui.py](../src/perp_farming_bots/ui.py) | [test_account_form.py](../tests/test_account_form.py) |
| Native orders, fees and signing | [trading.py](../src/perp_farming_bots/trading.py), [entropy.py](../src/perp_farming_bots/entropy.py) | [test_trading.py](../tests/test_trading.py), [test_entropy.py](../tests/test_entropy.py) |
| Ownership, hedge entry/close or restart | [runtime.py](../src/perp_farming_bots/runtime.py), [store.py](../src/perp_farming_bots/store.py) | [test_runtime.py](../tests/test_runtime.py), [test_lifecycle.py](../tests/test_lifecycle.py) |
| Timed reopening and random wait | [runtime.py](../src/perp_farming_bots/runtime.py), [store.py](../src/perp_farming_bots/store.py) | [test_reopening.py](../tests/test_reopening.py) |
| Network reads and prolonged outages | [markets.py](../src/perp_farming_bots/markets.py), [runtime.py](../src/perp_farming_bots/runtime.py), [grid.py](../src/perp_farming_bots/grid.py) | [test_network_reads.py](../tests/test_network_reads.py), [test_read_outages.py](../tests/test_read_outages.py), [test_grid_quotes.py](../tests/test_grid_quotes.py) |
| Grid sizing, startup and execution | [grid.py](../src/perp_farming_bots/grid.py), [grid_ui.py](../src/perp_farming_bots/grid_ui.py) | [test_grid.py](../tests/test_grid.py), [test_grid_startup.py](../tests/test_grid_startup.py), [test_grid_preflight.py](../tests/test_grid_preflight.py) |
| Grid edits, closed-bot reuse or layout evidence | [store.py](../src/perp_farming_bots/store.py), [grid.py](../src/perp_farming_bots/grid.py) | [test_grid_reuse.py](../tests/test_grid_reuse.py) |
| Margin configuration | [margin.py](../src/perp_farming_bots/margin.py), [native_margin.py](../src/perp_farming_bots/native_margin.py) | [test_margin.py](../tests/test_margin.py), [test_grid_preflight.py](../tests/test_grid_preflight.py) |
| Bot cards and strategy wall | [bot_widgets.py](../src/perp_farming_bots/bot_widgets.py), [strategy_widgets.py](../src/perp_farming_bots/strategy_widgets.py), [bot_styles.py](../src/perp_farming_bots/bot_styles.py) | [test_bot_management.py](../tests/test_bot_management.py), [test_strategy_widgets.py](../tests/test_strategy_widgets.py) |
| Funding | [markets.py](../src/perp_farming_bots/markets.py) | [test_funding.py](../tests/test_funding.py) |
| Points and history | [points.py](../src/perp_farming_bots/points.py), [points_widgets.py](../src/perp_farming_bots/points_widgets.py) | [test_points.py](../tests/test_points.py), [test_points_history.py](../tests/test_points_history.py) |
| Schema and encrypted storage | [store.py](../src/perp_farming_bots/store.py), [security.py](../src/perp_farming_bots/security.py) | [test_store_schema.py](../tests/test_store_schema.py), [test_security.py](../tests/test_security.py) |

Fixture infrastructure lives in [tests/conftest.py](../tests/conftest.py). NiceGUI page callback tests are configured in [test_account_form.py](../tests/test_account_form.py); their pages execute against isolated Store/Runtime objects. Native read tests use HTTPX mock transport. Production adapters stay out of test doubles and production runtime stays out of fixture data.

## Adding a venue or strategy

For a venue, inspect the `Adapter` interface in [trading.py](../src/perp_farming_bots/trading.py): validate, snapshot, prepare, send, lookup, open_orders and margin methods. Implement concrete native identity and public market precision in addition to signing. `prepare` must not submit. `send` must preserve single-send behavior. `lookup` must confirm original identity and terminal quantities; missing evidence remains unknown. Register only an implemented account path, document official source/unit/fee/recovery evidence, and update the venue tests and [UPSTREAMS.md](../UPSTREAMS.md).

For a strategy, define explicit typed parameters, account reservations, entry/exit rules, owned inventory, budgets, pending operation semantics and pause/close/restart behavior. Keep shared native execution in Runtime and accounting in Store. Add a usable form and read-only monitor before registering the strategy. Do not introduce a DSL, dynamic remote strategy loading or a disabled placeholder.

Document which evidence is isolated testing, public read connectivity, authenticated read validation or funded acceptance. Do not treat one level as another.

## Documentation and release hygiene

- README files are short entry points; [docs/README.md](README.md) routes readers to one authoritative subject document.
- Source definitions are authoritative: models for accepted inputs, Store for schema/ownership, Runtime/Grid for execution, and `uv.lock` for installed versions.
- Protocol research keeps public sources, pins, dates and unit interpretations. Remove conversation history and machine-specific incident narratives from published documentation.
- Run `make docs-check`; it validates repository-relative Markdown links and heading anchors without external requests.
- Keep `.env`, `data/`, private captures, keys and database backups untracked. Review staged files before pushing. Refer to [Operations](operations.md) for actual data handling.
- Describe changes and relevant verification in the PR. Avoid fixed test-count claims in repository docs; the suite grows.
