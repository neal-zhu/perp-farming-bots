# Upstream provenance register

This repository now includes independently written application code, tests and planning documents. Public dependencies are pinned in uv.lock, including the official Lighter SDK at commit 04bee9ba9811b87ef1cccc568e7f590b5fe649bb. The grid includes a small attributed adaptation of Hummingbot’s public grid geometry utility. No private project has supplied implementation artifacts.

| Upstream | Role | Verified license | Intended use |
| --- | --- | --- | --- |
| [elliottech/lighter-python](https://github.com/elliottech/lighter-python) | Lighter/RH public SDK | Apache-2.0 source LICENSE | Installed pinned native signing SDK; real-order code path, not funded-order certified |
| [hyperliquid-dex/hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk) | Entropy mainnet EIP-712 action signing | MIT, official LICENSE.md | PyPI 0.24.0 pinned; signing only, HTTP submits through the existing durable journal |
| [ccxt/ccxt](https://github.com/ccxt/ccxt) | Other REST/WS connectors | MIT | Evaluated for later adapters; not currently a runtime dependency |
| [sethmlarson/truststore](https://github.com/sethmlarson/truststore) | OS certificate trust | MIT | Explicit HTTPX SSLContext |
| [python-websockets/websockets](https://github.com/python-websockets/websockets) | Read-only native funding stream | BSD-3-Clause | Short public market_stats subscriptions with verified TLS |
| [zauberzeug/nicegui](https://github.com/zauberzeug/nicegui) | Browser UI | MIT | Dependency |
| [fastapi/fastapi](https://github.com/fastapi/fastapi) | HTTP/lifecycle | MIT | NiceGUI dependency and application routes |
| [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) | Persistence | MIT | Dependency |
| [arcus-xyz/arcus-spot-sdk](https://github.com/arcus-xyz/arcus-spot-sdk) | Official spot SDK | Apache-2.0 | Research only; no perp substitution |
| [elliottech/lighter-agent-kit](https://github.com/elliottech/lighter-agent-kit) | Official onboarding/scripts | MIT | Research only |
| [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | Grid strategy reference / pure geometry | Apache-2.0 | Adapted Distributions.linear; full engine not installed |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | Complete trading framework | LGPL-3.0 | Evaluated alternative; current source/release distinction matters |

See docs/research/ for actual reviewed commit IDs and support evidence. License compatibility conclusions apply only to the selected architecture and verified versions; notices from actual transitive dependencies and bundled frontend/native assets must be included when packaging.

If public code is copied rather than imported as a dependency, append its exact repository, commit, original path, local path, license and required attribution here. Do not imply that source availability alone grants redistribution rights.

SDK-provided referral/builder/integrator defaults are reviewed separately from code licenses. The product must not add hidden referral links or fees. Disable optional defaults explicitly; where their absence cannot be verified, do not certify that adapter for live execution.

The Lighter source LICENSE is Apache-2.0, while the pinned pyproject metadata labels its license as NoLicense. This discrepancy is recorded rather than silently treating package metadata as a license grant; source LICENSE and any native artifact notices need to be retained for distribution. Current application uses the native signer to prepare user-selected orders, and independently submits journaled native requests. No referral or integrator write function is called. Arcus signing is independently implemented from the official protocol documentation; its spot SDK supplies no perpetual execution code.

Points protocol evidence is recorded in [docs/research/points.md](docs/research/points.md). Official API definitions and Arcus's publicly served frontend were inspected only to establish endpoint and authorization semantics. No frontend source was copied or vendored. Points statistics use read-only endpoints; no referral registration, reward claim or program enrollment is performed.

## Grid source reuse (2026-10-13)

Hummingbot commit `9af100d6822da7d2d0291a906c730ef172284ee2`, original `hummingbot/strategy_v2/utils/distributions.py::Distributions.linear`, is adapted in `src/perp_farming_bots/hummingbot_grid.py`. Changes: Decimal-only inputs, invalid-input rejection, isolated function and formatting. The original Apache-2.0 LICENSE and local attribution are in `third_party/hummingbot/`, included in wheel and Docker packaging. GridExecutor is an architectural reference, not an imported executor or a claim of equivalent venue acceptance. Detailed reviewed sources and differences: [grid research](docs/research/grid.md).

## Entropy protocol integration (2026-10-14)

See [Entropy evidence](docs/research/entropy.md). The official frontend and public market API were inspected for native market identity, builder address and fee settings; no frontend implementation was copied. Orders explicitly use Entropy’s builder code with zero added builder fee. No app-owned builder, referral code, wallet transfer, agent creation or approval action is submitted. The official SDK is used as a dependency for `sign_l1_action`; its HTTP client and optional builder defaults are not used.
