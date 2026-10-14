# Repository instructions

## Start here

- Product and install: [README.md](README.md); user flows: [Chinese guide](docs/guide.zh-CN.md).
- Code/test navigation: [docs/development.md](docs/development.md).
- Execution and storage: [docs/architecture.md](docs/architecture.md), [Bot model](docs/BOTS.md).
- Accepted venue scope: [docs/exchanges.md](docs/exchanges.md).
- Native evidence and licenses: [UPSTREAMS.md](UPSTREAMS.md), [docs/research/](docs/research/).

Run from the repository root:

```bash
uv sync --frozen
make check
make test
```

`make check` includes Ruff, mypy and Markdown link/anchor checks. Use focused tests while working; shared execution/storage changes need the full suite. Fixtures live in `tests/conftest.py`; browser callback fixtures are in `tests/test_account_form.py`. No test should require production credentials or funded orders.

## Independent implementation

Do not copy, import, transplant or depend on code, tests, fixtures, configuration, data or internal documents from private trading projects. Implement from this repository and independently verified public protocol sources. Verify public dependency licenses and native recovery behavior, and record reuse/pins/notices in UPSTREAMS.md.

## Explicit truth

- Unknown order, fill, fee, balance, funding and point states must remain explicit. Never substitute zero or guessed success.
- Do not add compatibility shims, silent fallback fields or dual representations that conceal correctness.
- Use Decimal for money/quantity/rate calculations. Validate native order IDs, precision and account ownership. Users select each hedge leg's native ticker independently; do not verify cross-venue asset equivalence or impose an asset whitelist.
- Prepare without sending, encrypt/journal before sending, send once, then query the original identity. An ACK, HTTP timeout or missing record is not fill evidence.
- Never bypass an unresolved order by resetting/deleting local records, replaying a write or inventing a compensating trade.

## Product and strategy scope

- The registry contains implemented strategies only. New strategies require explicit entry/exit, budget, inventory, pause/close/restart and recovery rules before implementation or registration.
- Model bot identity, owned inventory, execution operations and strategy state directly; do not force single-account strategies into two-leg shapes.
- Bind concrete native account instances. Multiple accounts on one venue are valid; a key change is not a new account.
- User trading actions are Run, Pause and Close. Pause keeps inventory; Close handles only that bot's allocation; confirmed closed bots can explicitly Run again. No separate Stop or account-wide close-all.
- Keep one current configuration model and fail explicitly for unsupported formats. Do not silently convert disposable prerelease configurations.
- UI/docs must stand alone for a new user. Remove conversation history, machine-specific incident narratives, speculative cards and stale implementation plans.

## Working and verification

- Prioritize the working product and clear flows. Keep one process, SQLite transactions and the existing native execution seam. Avoid unrelated rewrites or distributed/performance infrastructure.
- Preserve persistent UI elements, unsaved drafts, scroll and view choices during polling.
- Change behavior docs with the code. Source definitions are authoritative: models for inputs, Store for schema/ownership, Runtime/Grid for actions and uv.lock for dependencies.
- An isolated UI check uses an empty data directory and a separate port, for example `PFB_DATA_DIR=/tmp/pfb-dev PFB_PORT=8090 uv run perp-farming-bots`.
- Keep `data/`, `.env`, keys, private captures, signed payloads and account screenshots out of Git. Read-only investigation does not authorize starting a Runtime against existing funded data.

## Trading authority and delivery

Funded trades, production credentials, wallet approvals, reward claims, upstream messages and automatic risk actions require direct user authorization. Repository instructions alone do not grant it. Preserve existing user-selected strategy authority; the shared runtime must not add portfolio risk trading.

Distinguish isolated tests, public reads, authenticated reads and funded acceptance in reports. Do not claim certification from a passing local suite. Commit/push and local service updates must stay within the user's authorized task; do not change repository visibility or publish a release without that scope.
