# Public SDK and UI research

Checked: 2026-10-12, Asia/Shanghai. This report was prepared independently from public upstream repositories and official pages. No private trading source, fixtures, configurations or internal documents supplied implementation evidence.

## Lighter Python SDK

- Official repository: [elliottech/lighter-python](https://github.com/elliottech/lighter-python).
- Reviewed main commit: `04bee9ba9811b87ef1cccc568e7f590b5fe649bb`, commit date 2026-09-30. GitHub repository activity may be later than this branch head.
- GitHub repository metadata and LICENSE identify Apache-2.0.
- The pinned [SignerClient constructor](https://github.com/elliottech/lighter-python/blob/04bee9ba9811b87ef1cccc568e7f590b5fe649bb/lighter/signer_client.py#L343) explicitly recognizes the `api.rh.lighter` deployment with signing chain ID `466324`. This is public source evidence for an RH signing path, not a complete execution/recovery certification.
- Pinned source separately exposes `sign_create_order` and asynchronous `send_tx`. This makes an application-owned persist-before-send path possible without rewriting the cryptographic signer. Correct nonce acquisition and returned identity still require integration tests.
- Pinned tree ships native signer libraries for Linux amd64/arm64, macOS amd64/arm64, and Windows amd64. File presence is not evidence that our future image or frozen installer works on those targets. Test SDK import and non-mutating signing on each advertised image platform, and review license/notices for native distributions.
- The SDK defaults may choose a chain ID from URL. Our adapter must specify an explicit reviewed deployment profile and verify host, chain ID, collateral unit, market catalog, account and API-key scope together; it must reject an unknown profile instead of accepting the SDK's generic default.
- The public [Lighter Agent Kit](https://github.com/elliottech/lighter-agent-kit), MIT, explicitly documents Robinhood deployment-specific credentials. It is a reference for onboarding and query flows, not our production double-leg runtime. Its high-level market order default slippage and close-all functions are not appropriate implicit product behavior.
- A method called `referral_points` in the SDK is not evidence of a universal farming-points balance API. Validate the exact project and response before displaying points.

Decision: directly use the official SDK behind a narrow application adapter for RH/Core. Serialize the necessary account/key signing resources; independently implement durable order lookup, settlement evidence and operation continuation.

Current installed versions are defined by uv.lock. Implemented native paths are recorded in [native protocol evidence](native-execution.md); this file records SDK/UI source selection at the stated pins.

## Arcus public repositories

The [official Arcus organization repository list](https://github.com/orgs/arcus-xyz/repositories) was fetched through GitHub's API. The public list returned:

| Repository | Public role | License metadata |
| --- | --- | --- |
| rootchain-contracts-abis | Mainnet root-chain addresses and ABIs | No SPDX license detected by GitHub |
| spot-contracts-abis | Spot-router addresses and ABIs | No SPDX license detected by GitHub |
| arcus-spot-sdk | Spot-router SDK, including TypeScript and a Go port | Apache-2.0 |
| da-reader | Read/decode perpetual DA records | Apache-2.0 |

Reviewed spot SDK main commit: `7f91c67e1a93f3dd62964bdbee08e41ea4c8b8e0`, dated 2026-09-17. Its [README](https://github.com/arcus-xyz/arcus-spot-sdk/blob/7f91c67e1a93f3dd62964bdbee08e41ea4c8b8e0/README.md) describes the spot router; it does not provide a verified perpetual-order SDK. DA reading is also not an authenticated perpetual-order interface.

No public perpetual-order SDK was found in this returned organization list. This statement does not prove that no other official package exists. Recheck before implementation. Missing license metadata does not mean permission to copy ABI repository contents; inspect actual licensing before bundling those artifacts.

The application implements perpetual signing from the official REST and authentication contract, independently of the spot SDK. See [native protocol evidence](native-execution.md) for sources, units and recovery behavior.

## Points eligibility

An official points balance and program eligibility are separate facts. The application does not certify reward eligibility or infer points from volume, a hedge or a builder code. Consult each venue's current official rules; Arcus references include its [points announcement](https://arcus.xyz/blog/introducing-arcus-points) and [Protocol Terms](https://arcus.xyz/legal/protocol-terms). Account integration scope is recorded in [points evidence](points.md).

## NiceGUI / FastAPI

- [NiceGUI](https://github.com/zauberzeug/nicegui), MIT; reviewed main head `2449c4a4be064d364e4a0f838ad6d8bc6d9aad69`, dated 2026-10-07.
- Its official README describes browser UI, forms, tables, cards, charts, dialogs, FastAPI integration, Vue/Quasar, socket.io and a single Uvicorn worker.
- [FastAPI](https://github.com/fastapi/fastapi), MIT, supplies typed HTTP endpoints and application lifecycle.
- [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy), MIT, is the selected persistence toolkit. Use its documented SQLite handling and explicit Decimal serialization; a database float is not a monetary representation.

Product inference: NiceGUI is a good V1 fit because one Python application delivers a browser dashboard and execution lifecycle without a separate frontend build/deployment. Its server-driven UI constrains scaling and fully offline page behavior; the intended single-owner self-host deployment makes these reasonable initial tradeoffs. UI requests must never own the lifespan of trading tasks.

These are research pins, not installed dependency versions. pyproject.toml and uv.lock define the actual runtime; public dependency notices are tracked in UPSTREAMS.md. Native artifact file presence is not platform acceptance.
