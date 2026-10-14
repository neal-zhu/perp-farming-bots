# Contributing

Read [AGENTS.md](AGENTS.md) before making changes. The [development map](docs/development.md) links each feature to its implementation and tests.

## Set up

Install Git and [uv](https://docs.astral.sh/uv/getting-started/installation/), clone the repository, then:

```bash
uv sync --frozen
make check
make test
```

`uv.lock` is committed. Change dependencies through `uv add` or `uv remove`, verify the upstream license and native behavior, and update [UPSTREAMS.md](UPSTREAMS.md). Use Python 3.12 for the supported baseline. There is no Node build step.

To inspect the UI without using an existing trading instance, choose a separate empty data directory and port:

```bash
PFB_DATA_DIR=/tmp/pfb-dev PFB_PORT=8090 uv run perp-farming-bots
```

This starts an empty application with real venue adapters. Tests use isolated doubles; the application has no simulated trading mode. Do not attach production credentials for automated UI checks. Do not click Run or Close on a funded bot as part of routine verification.

## Make a change

1. Locate the owning module and its tests in [docs/development.md](docs/development.md).
2. Keep request validation, native evidence and bot inventory ownership explicit. Use Decimal for money and quantities.
3. Add a focused regression test when trading behavior, recovery or ownership changes. Keep venue responses and keys test-only.
4. Update the relevant user or technical document when observable behavior changes.
5. Run `make check` and the relevant tests, then `make test` for changes affecting shared execution or storage.

The project uses Ruff and mypy. Keep the existing style; avoid unrelated formatting or architectural rewrites. Documentation prose should describe current behavior without conversational history or speculative features. Run `make docs-check` after editing Markdown.

## Propose new execution behavior

A new strategy needs concrete entry/exit rules, budget and inventory semantics, pause/close/restart behavior and evidence for completing an operation. An exchange adapter needs native identity, precision, credentials, signing, single-send submission and original-order lookup. Do not add an unavailable strategy card as a substitute for an implementation.

Read the [extension checklist](docs/development.md#adding-a-venue-or-strategy) and record official protocol sources in `docs/research/`. Public SDK availability alone does not establish funded-order acceptance, native fees or reward eligibility.

## Submit a pull request

Describe the concrete problem, resulting behavior and validation performed. State any material venue or data limitations. Do not include account identifiers, credentials, local databases, signed requests or screenshots of funded accounts. Changes to trading authority need explicit scope in the description.

Use the local [bug report](.github/ISSUE_TEMPLATE/bug_report.yml) or [feature request](.github/ISSUE_TEMPLATE/feature_request.yml) templates to provide reproducible, redacted reports. Vulnerability reports follow [SECURITY.md](SECURITY.md).
