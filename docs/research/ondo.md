# Ondo Perps native protocol evidence

Reviewed 2026-10-14 against public primary sources. This note concerns the **Ondo Perps venue**, not an ONDO-token contract on another exchange or Ondo Global Markets mint/redeem APIs. No private project supplied implementation artifacts. No wallet login, credential creation, transfer, approval or funded order was performed during research.

## Venue and reviewed sources

- [Official Ondo Perps introduction](https://ondo.finance/blog/introducing-ondo-perps) identifies the product. Its [official documentation](https://docs.ondoperps.xyz/about) and [documentation index](https://docs.ondoperps.xyz/llms.txt) describe the venue and its account/trading APIs.
- The official [REST OpenAPI document](https://docs.ondoperps.xyz/api-reference/rest-spec.json), retrieved on the review date, declares OpenAPI `3.0.3`, title `Ondo Perps REST API`, version `1.0`, production server `https://api.ondoperps.xyz`. The retrieved bytes have SHA-256 `3fcae9abb9395a9460d60d0dd762e0c550af884bd7723e6a8648747ee6609fe8`. This is a reviewed snapshot fingerprint, not a runtime schema pin.
- [LI.FI's Ondo provider](https://github.com/lifinance/perps-sdk/tree/233d9fda0e3f2c4b1a6e1ca8e1d65af813c10f31/packages/perps-sdk-provider-ondo) was reviewed at commit `233d9fda0e3f2c4b1a6e1ca8e1d65af813c10f31`; its package version is `29.0.0`. The repository [license](https://github.com/lifinance/perps-sdk/blob/233d9fda0e3f2c4b1a6e1ca8e1d65af813c10f31/LICENSE) and [package manifest](https://github.com/lifinance/perps-sdk/blob/233d9fda0e3f2c4b1a6e1ca8e1d65af813c10f31/packages/perps-sdk-provider-ondo/package.json) specify Apache-2.0. This is third-party maintained protocol implementation evidence, not a first-party Ondo SDK or acceptance certification.
- No first-party Python Perps SDK was linked in the reviewed official documentation. The official authentication page provides a Python standard-library HMAC example; importing a whole TypeScript trading engine is unnecessary for this signature.

## Account credentials and unattended reads

[API key authentication](https://docs.ondoperps.xyz/api-reference/api_key_authentication) instructs users to sign into the venue in a browser, open the address menu, select **API Keys**, add a named key, select permissions and preserve the secret displayed once. The application can accept an existing key and secret without storing the user's main-wallet private key or a short-lived browser JWT. The same page supports IP whitelisting with up to 16 IPv4 addresses; an empty whitelist accepts all source IPs.

The native key ID retains the `ondoKeyId_` prefix; its secret retains `ondoApiSecret_`. Each authenticated request sends `ONDO-KEY-ID`, `ONDO-TIMESTAMP` and `ONDO-SIGN`. The signature is lowercase hexadecimal HMAC-SHA256 keyed by the complete UTF-8 secret over the concatenation of:

```text
timestamp_ms + uppercase_http_method + exact_path_including_query + exact_body_bytes
```

There are no separators. A bodyless GET signs an empty body. Query order and URL escaping must match the request actually sent. The official timestamp window permits at most **10 seconds behind or 1 second ahead** of server time. The reviewed [LI.FI HMAC helper](https://github.com/lifinance/perps-sdk/blob/233d9fda0e3f2c4b1a6e1ca8e1d65af813c10f31/packages/perps-sdk-provider-ondo/src/auth/hmac.ts) agrees with the byte construction but comments a 30-second window; the official 10-second/1-second rule is authoritative.

The REST schema explicitly permits either `BearerAuth` or `ApiKeyAuth` for account, key-list, order, fill, position, balance and leverage reads, as well as perpetual order/leverage writes. Therefore ongoing reads can use freshly signed HMAC requests and do not require wallet-signature JWT renewal. The reviewed Perps `ApiKeyScope` enum contains `trade` and `transfer`; it does not establish a separate Perps `view` permission. The official [API-key frontend asset](https://app.ondoperps.xyz/_next/static/chunks/pages/account/api-keys-cc53746c4cb7b313.js) labels an empty scope array as view-only and `['trade']` as view-and-trade. The application needs the trading key and no transfer permission. Spot documentation has distinct permission semantics and is not a substitute for the perpetual schema.

[Get Account](https://docs.ondoperps.xyz/api-reference/account/get-account) returns `accountID`, `identifier` (wallet address or email), `authType`, `accountState` and optional disabled-feature flags. [List API Keys](https://docs.ondoperps.xyz/api-reference/api-keys/list-api-keys) returns key IDs, scopes and IP restrictions without returning secrets. Validate the supplied key against the authenticated account's registry and bind the concrete native account ID. A key rotation must not invent a new account. Reject a disabled account or explicitly disabled Perps functionality.

No perpetual subaccount selection/header contract was found in the reviewed REST schema. The API-key frontend does contain `ONDO-SUBACCOUNT-ID` and `/v1/subaccounts/{id}/api_keys`, establishing that the venue has account-selection functionality beyond this schema. That does not establish how an imported HMAC key should safely switch account scope. Do not infer a subaccount from an address, numeric alias or `subaccountsLimit`. Any later subaccount support needs its own primary identity/routing evidence.

The LI.FI [signing workflow](https://github.com/lifinance/perps-sdk/blob/233d9fda0e3f2c4b1a6e1ca8e1d65af813c10f31/packages/perps-sdk-provider-ondo/src/auth/signActions.ts) also includes SIWE login, API key creation/revocation and account setup; its [defaults](https://github.com/lifinance/perps-sdk/blob/233d9fda0e3f2c4b1a6e1ca8e1d65af813c10f31/packages/perps-sdk-provider-ondo/src/constants.ts) request `trade` **and** `transfer`. Those actions/defaults are not needed for this product's trading adapter. Use an existing trading key; do not create, revoke, transfer or attach a referral automatically.

## Prepared orders and original-identity recovery

[Create Order](https://docs.ondoperps.xyz/api-reference/orders/create-order) uses `POST /v1/perps/orders`. Native limit IOC fields are:

| Field | Required application evidence |
| --- | --- |
| `market` | Exact selected native identifier, for example `AAPL-USD.P` |
| `side` | `buy` or `sell` |
| `type` | `limit` |
| `timeInForce` | `IOC` |
| `size` | Decimal base quantity aligned to that market's `baseIncrement` |
| `price` | Decimal limit price aligned to `quoteIncrement` |
| `clientOrderId` | Unique original ID, at most 64 characters, using alphanumeric characters, underscores or dashes |
| `reduceOnly` | Explicit application-selected boolean |
| `postOnly` | `false` for this IOC execution path |

Prepare exact body and HMAC headers without sending, persist them in the encrypted order journal, then submit that original payload once. Signature timestamps are request-authentication material; they are not a client-order identity or documented idempotency key. Once a write is uncertain, an expired signature does not authorize re-signing/replaying that write.

[Get Order by ID](https://docs.ondoperps.xyz/api-reference/orders/get-order-by-id) supports `GET /v1/perps/orders/{orderID}` where the path value is either a native internal order ID or `client:{clientOrderId}`. [Get Fills by Order ID](https://docs.ondoperps.xyz/api-reference/fills/get-fills-by-order-id) supports the corresponding `/fills` path and documents returning all fills for that order. URL-encode the path value and sign precisely that encoded request path. Recovery signs a new **read** against the original ID.

The native `ApiOrder` lifecycle is `open`, `pending`, `untriggered`, `fullyfilled` or `canceled`. Only `fullyfilled` and `canceled` are terminal. A canceled IOC may have nonzero `filledSize`. The returned native order must match the original client ID, market, side, type, size, limit price, time in force and reduce-only flag before applying its result. Missing optional identity fields are missing evidence, not permission to substitute defaults.

`filledSize`, `filledCost` and `fee` are native order aggregates. Fill records carry unique `id`, `orderId`, market, side, quantity, price, cost, fee and timestamp. Validate each fill against the native order identity and require complete aggregate agreement before applying inventory or turnover. An ACK or an open order is not proof of completion. `order_not_found`, missing results, malformed rows, duplicate/conflicting fill IDs or incomplete fills remain unknown.

The create endpoint publishes explicit validation/error codes including `clientOrderID_collision`, `must_use_delayed_path` and `redirect`. A collision cannot be treated as proof that the original write failed. No documented automatic retry/idempotent replacement contract was found. Do not follow an arbitrary write redirect, switch to a delayed path or replay the original order. A separately understood, explicit native rejection can be recorded as rejection; a timeout, connection failure or unclassified response still requires original-ID recovery.

## Published minimum-order evidence

The official [market API](https://docs.ondoperps.xyz/api-reference/markets/get-markets) and perpetual order schema expose `baseIncrement` and `quoteIncrement`. The official [Perps frontend asset](https://app.ondoperps.xyz/_next/static/chunks/1496.34ff21c9a445cc97.js), reviewed without copying its implementation, checks the Perps base amount against `baseIncrement` and renders that increment as the minimum quantity. This establishes the published UI quantity floor of one base increment.

No separate **Perps** minimum-notional value or guarantee that no such floor exists was found in the reviewed REST schema, [complete official documentation corpus](https://docs.ondoperps.xyz/llms-full.txt) or Perps form validator. The explicit rule that no independent notional floor exists in the [Spot API guide](https://docs.ondoperps.xyz/api-reference/spot-api-guide) applies to Spot and cannot establish a perpetual rule. Model the unpublished perpetual notional floor as unknown; do not assign `0` merely because the metadata omits it.

## Fees, balance and position semantics

[Fees](https://docs.ondoperps.xyz/fees) specifies that Perps fees are charged in **USDC** on filled notional. Referral rebates reduce net trading fees. `ApiOrder` and `ApiFill` expose `fee` and optional `feeRebate`; the reviewed [LI.FI fill mapper](https://github.com/lifinance/perps-sdk/blob/233d9fda0e3f2c4b1a6e1ca8e1d65af813c10f31/packages/perps-sdk-provider-ondo/src/utils/mapFill.ts) and the official Perps frontend asset subtract rebate from fee. Verify monetary aggregates independently; a malformed/missing monetary field remains unknown. The primary schema does not state that an absent optional rebate proves zero. The official frontend also converts malformed money to zero, so its helper is not suitable for native execution evidence. Do not adopt that fallback as protocol truth.

The fee page separately describes an optional builder commission added to base fees. Orders should omit `builderCode` unless the user explicitly selects a supported attribution scheme. Do not inject an app-owned builder, hidden commission or referral binding. Promotional/base fee schedules are not a substitute for the user's actual native fill fees.

[Get Balance](https://docs.ondoperps.xyz/api-reference/margin-account/get-balance) uses `GET /v1/perps/balance`. `marginBalance`, `usedMargin` and `availableMargin` are USDC-valued native margin aggregates. [Positions, Balances, and Leverage](https://docs.ondoperps.xyz/positions-balances) defines available margin as margin balance minus used margin; it is distinct from withdrawable margin. Use native available margin for trading budget validation. The reported account `leverage` is effective exposure divided by margin, not the selected per-market leverage setting.

The venue supports [eligible non-USDC collateral](https://docs.ondoperps.xyz/balances), subject to haircuts/caps. A USDC-valued margin figure does not prove a spendable/on-chain USDC holding. This adapter need not transfer collateral, enable auto-exchange, withdraw funds or change collateral allocation to use the native trading-margin result.

[Get Positions](https://docs.ondoperps.xyz/api-reference/positions/get-positions) uses `GET /v1/perps/positions` and returns all open positions. `ApiPosition` includes market, direction (`long`, `short`, `neutral`), `netQuantity`, entry price, mark price, used margin, unrealized PnL and funding since neutral. Direction and quantity must be interpreted together; do not mistake an absent or malformed position row for a flat account.

Official positions documentation describes **cross-margin**: the account's full Perps margin balance supports its positions. No isolated-margin setting is documented. Per-market settings are read/written through `/v1/perps/leverage`; setting leverage requires the shared journaled margin workflow and read-back confirmation. A displayed bot investment is a strategy budget, not isolated collateral reserved by the venue.

## Verification boundary

The official docs/OpenAPI and public LI.FI source were retrieved and reviewed. Production API-root probing from the local research host returned HTTP 403; this alone does not establish an endpoint-specific or regional diagnosis. Account-authenticated reads and funded-order acceptance were not tested. Protocol schema review and isolated tests must be reported separately from those acceptance checks. Do not claim native trading certification solely from docs or a test suite.

Public endpoint-specific reads through the implemented adapter subsequently succeeded: 65 active perpetual markets, plus fresh `BTC-USD.P` and `AAPL-USD.P` depth and available hourly funding. The native market configuration supplies `marginInfo` leverage tiers; the first bracket supplies the highest configurable leverage. Order sizing still remains subject to native margin/position constraints. Funding uses the official [hourly settlement rule](https://docs.ondoperps.xyz/funding-rates), fractional rates multiplied by 100 for percentage display, and exact native `intervalEnds` timestamps. An upstream book timestamp is retained rather than replaced by local receipt time.

Imported key IDs and secrets are encrypted together with the bound native account ID. The existing database schema is unchanged. Minimum-notional metadata and grid minimum-budget estimates stay `null` when not verified; published quantity constraints can still be checked without representing the omitted floor as zero. Current snapshots and original-client-ID lookups verify the bound account before using trading evidence. Known create-order validation rejections are recorded as rejected; duplicate client IDs, delayed routes, redirects, missing orders and transport failures remain unconfirmed and cannot enable a peer leg. Net fee accounting requires complete gross-fee and rebate evidence, including an explicit rebate value for each fill.
