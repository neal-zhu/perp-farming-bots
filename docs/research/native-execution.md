# Native execution protocol evidence

Read independently on 2026-10-12 (Asia/Shanghai). No private trading source, credentials, configurations or native captures were used. Protocol code is written in this application; public libraries are imported as dependencies.

## Arcus

Official primary sources, fetched successfully from this host:

- [REST guide](https://docs.arcus.xyz/guides/rest-trading.md)
- [Authentication](https://docs.arcus.xyz/api-reference/authentication.md)
- [Markets](https://docs.arcus.xyz/api-reference/public/get-markets.md)
- [Book](https://docs.arcus.xyz/api-reference/public/get-l2-orderbook-snapshot.md)
- [Account](https://docs.arcus.xyz/api-reference/public/get-account.md)
- [API keys](https://docs.arcus.xyz/api-reference/onboarding/get-api-keys.md)
- [Place order](https://docs.arcus.xyz/api-reference/exchange/place-order.md)
- [Order status/history](https://docs.arcus.xyz/api-reference/public/get-order-status.md)
- [Fills](https://docs.arcus.xyz/api-reference/public/get-fills.md)

The Ed25519 private API seed is 32 bytes. A typed canonical order payload is signed with integer ticks/quantums, lowercase wallet address, original case-sensitive client ID, nanosecond timestamp and mandatory future expiry. IOC still requires goodTilTime at least a month ahead; the application uses 40 days. HTTP acknowledgements are not fills. Native order history and matching fill rows establish quantity and fees; incomplete evidence remains unknown. Book paths use the native display name, such as BTC-USD, not the numeric ID. Arcus quote price and collateral accounting do not imply USDG/USDC conversion is handled.

This supersedes the earlier source-discovery finding that Arcus docs were inaccessible. Public metadata and actual BTC book connectivity succeeded. Private/account/order behavior still needs funded venue acceptance.

## Lighter

The pinned [official Python SDK](https://github.com/elliottech/lighter-python/tree/04bee9ba9811b87ef1cccc568e7f590b5fe649bb) supplies native signing. Core is explicitly chain 304 and RH chain 466324. Create/sign and HTTP send are separate so the signed request can be persisted first. The REST sendTx body is form-urlencoded, matching the pinned generated client; it is not JSON.

The application reads nextNonce for the exact account/key, signs a LIMIT IOC with expiry 0, and sends once. Terminal native order fields filled_base_amount and filled_quote_amount establish actual fill quantity and average price. A transaction hash does not establish an order fill. Missing actual fee history is reported as unknown.

Native signer selection is serialized and re-created for each use so equal account/key indices across deployments cannot share an accidentally selected signing domain. No builder/integrator parameters are enabled; pinned signer defaults are zero.

## TLS and scope

[Truststore](https://truststore.readthedocs.io/en/latest/) is an MIT dependency. HTTPX uses its explicit SSLContext, preserving certificate checks while trusting OS-managed certificate authorities. Actual Arcus/Core/RH public books were read with it. No insecure certificate bypass or generated quote fallback exists.

Initial executable pair assets are BTC, ETH and SOL: Arcus crypto perpetual base metadata and Lighter unit-multiplier 1 market metadata establish the units used here. RWA symbols and non-unit multipliers are excluded pending separate native-instrument review.
