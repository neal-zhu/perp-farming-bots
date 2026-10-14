# Exchange scope

Strategies accept BTC, ETH and SOL after native market precision and unit checks. A market catalog may list additional symbols; this does not expand the accepted strategy configuration. Unsupported instruments fail validation rather than being mapped by ticker resemblance.

| Provider ID | Native identity | Credential | Implemented scope |
| --- | --- | --- | --- |
| `arcus` | Lowercase wallet address + subaccount index 0–9 | Registered 32-byte Ed25519 API signing seed | Perpetual account, books, hourly funding, IOC orders, original-order/fill reads and margin settings |
| `lighter` | Core deployment + Account Index | API key index and native signing key | Account, books, hourly funding, IOC orders, original-order/trade reads and margin settings |
| `lighter_robinhood` | Robinhood deployment + Account Index | Deployment-specific API key index and key | Same execution scope; account live points and history |
| `entropy` | Lowercase main trading account address | Registered, unexpired Hyperliquid API agent key belonging to that account | Standard-DEX BTC/ETH/SOL, account, books, hourly funding, IOC orders, original-order/fill reads and margin settings |

Core and Robinhood use different hosts and signing chains. Matching account or key indices do not make them interchangeable. Entropy does not use numeric account/key indices. A new key for an existing native identity cannot create another independent account instance.

## Onboarding

- Arcus: [API Keys](https://app.arcus.xyz/api-keys), using the wallet address and the selected Subaccount #.
- Core: [API Keys](https://app.lighter.xyz/apikeys). Robinhood: [API Keys](https://robinhoodchain.lighter.xyz/apikeys). Select the matching deployment's Account Index and API key.
- Entropy: complete trading authorization through [Entropy](https://entropy.io), then create a named agent through [Hyperliquid API](https://app.hyperliquid.xyz/API) for the same main trading account. The application checks owner, expiry and existing Entropy builder approval through read-only native requests; it does not create wallet approvals.

User form instructions are in the [Chinese guide](guide.zh-CN.md#连接账户). The application accepts API signing keys, not a main wallet private key or seed phrase.

## Explicit exclusions and data limits

- Entropy unified/portfolio-margin accounts, subaccounts, vaults and native `io:*` HIP-3 instruments are not implemented. Entropy orders include its verified official builder with zero added builder fee; this does not establish points eligibility.
- Direct Hyperliquid and Binance account adapters are not implemented. Their provider identifiers in the API catalog are marked `account_implemented=false` and cannot be selected to connect an account.
- Arcus, Core and Entropy points are not integrated. Robinhood reads only the official account live total; no global sum or bot points allocation is inferred.
- Lighter zero monetary fees require complete native trade evidence. Nonzero fee rates do not become verified monetary fees by assumption; fees can remain unknown.
- Actual funding payments are not attributed to bots and are excluded from trading PnL. Funding forecasts retain their own source/time and status.
- Order history is bounded by native endpoints. Missing or truncated evidence remains unknown and blocks fresh execution; it is never assumed to be a zero fill.

## Verification and provenance

Isolated tests cover protocol parsing, signing inputs, identity, ownership and recovery. Public read probes have verified market/funding connectivity for the implemented providers. Funded-order acceptance is not certified across all providers, account profiles or platforms. Treat these as separate evidence levels.

Official references and implementation-specific interpretation: [native execution](research/native-execution.md), [Entropy](research/entropy.md), [margin](research/margin.md), [points](research/points.md). Dependency pins and notices: [UPSTREAMS.md](../UPSTREAMS.md).
