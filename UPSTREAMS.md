# Upstream provenance register

This repository currently contains original planning documents and repository policy only. No upstream application code has been vendored, no trading dependency has been installed, and no private project has supplied implementation artifacts.

| Upstream | Role | Verified license | Intended use |
| --- | --- | --- | --- |
| [elliottech/lighter-python](https://github.com/elliottech/lighter-python) | Lighter/RH public SDK | Apache-2.0 | Dependency after version and native signer checks |
| [ccxt/ccxt](https://github.com/ccxt/ccxt) | Other REST/WS connectors | MIT | Dependency; individually certified venues |
| [zauberzeug/nicegui](https://github.com/zauberzeug/nicegui) | Browser UI | MIT | Dependency |
| [fastapi/fastapi](https://github.com/fastapi/fastapi) | HTTP/lifecycle | MIT | NiceGUI dependency and application routes |
| [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) | Persistence | MIT | Dependency |
| [arcus-xyz/arcus-spot-sdk](https://github.com/arcus-xyz/arcus-spot-sdk) | Official spot SDK | Apache-2.0 | Research only; no perp substitution |
| [elliottech/lighter-agent-kit](https://github.com/elliottech/lighter-agent-kit) | Official onboarding/scripts | MIT | Research only |
| [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | Complete trading framework | Apache-2.0 | Evaluated alternative |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | Complete trading framework | LGPL-3.0 | Evaluated alternative; current source/release distinction matters |

See docs/research/ for actual reviewed commit IDs and support evidence. License compatibility conclusions apply only to the selected architecture and verified versions; notices from actual transitive dependencies and bundled frontend/native assets must be included when packaging.

If public code is copied rather than imported as a dependency, append its exact repository, commit, original path, local path, license and required attribution here. Do not imply that source availability alone grants redistribution rights.

SDK-provided referral/builder/integrator defaults are reviewed separately from code licenses. The product must not add hidden referral links or fees. Disable optional defaults explicitly; where their absence cannot be verified, do not certify that adapter for live execution.
