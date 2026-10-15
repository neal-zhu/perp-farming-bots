# Documentation

User-facing onboarding is in Simplified Chinese, matching the current web interface. Contributor and agent references are in English. These documents describe the checked-in implementation; protocol research records dated upstream evidence rather than future product promises.

| Task | Start here |
| --- | --- |
| Install and connect an account | [中文快速开始](../README.zh-CN.md), [使用指南](guide.zh-CN.md) |
| Create trading API keys and fill the connection form | [API 配置图文指南](api-setup.zh-CN.md) |
| Understand supported venues and points | [Exchange scope](exchanges.md) |
| Configure, back up or restart an instance | [Operations](operations.md) |
| Understand a bot and its ownership | [Bot model](BOTS.md) |
| Understand spread entry and timed reopening | [Spread hedging](hedging.md) |
| Understand grid sizing and trigger rules | [Grid](GRID.md) |
| Find the implementation or relevant tests | [Development map](development.md) |
| Understand execution, storage and recovery | [Architecture](architecture.md) |
| Use the local API | [API reference](api.md) |
| Contribute with a coding agent | [llms.txt](../llms.txt), [AGENTS.md](../AGENTS.md), [Contributing](../CONTRIBUTING.md) |
| Review access and secret boundaries | [Security scope](../SECURITY.md) |
| Check licensing and reused code | [Upstream register](../UPSTREAMS.md) |

## Protocol evidence

- [Arcus/Lighter execution and funding](research/native-execution.md)
- [Entropy signing, account scope and recovery](research/entropy.md)
- [Ondo Perps authentication, native orders and limits](research/ondo.md)
- [Margin units and configuration](research/margin.md)
- [Account points and collection](research/points.md)
- [Entropy points API investigation](research/entropy-points.md)
- [Grid reference and adaptation](research/grid.md)
- [SDK and UI source evaluation](research/sdk-and-ui.md)
- [Framework comparison](research/frameworks.md)

`pyproject.toml` and `uv.lock` define installed dependencies. `models.py` defines accepted configuration and strategy types. `store.py` defines the current database schema. Research documents do not override those sources.
