# Local HTTP API

Routes: [api.py](../src/perp_farming_bots/api.py). Request/response models: [models.py](../src/perp_farming_bots/models.py). The current NiceGUI server does not expose an interactive Swagger page at `/docs`.

The UI and API share the same Runtime/Store and have no authentication. Use localhost or the supported SSH tunnel. **Strategy configuration is separate from trading authority:** Save does not start a bot; Run enables background execution and grid native margin settings.

## Endpoints and effects

| Method and path | Effect |
| --- | --- |
| `GET /health` | Service heartbeat; does not certify venue health |
| `GET /api/catalog` | Implemented strategy definitions and provider capability flags |
| `GET /api/connections` | Public metadata and current snapshot/status; no private keys |
| `POST /api/connections` | Read-validate native credentials, then save encrypted local configuration |
| `POST /api/connections/{id}/refresh` | Refresh native account reads |
| `DELETE /api/connections/{id}` | Remove eligible local connection; no native close |
| `GET /api/connections/{id}/markets` | Native catalog, broader than accepted strategy assets when applicable |
| `GET /api/connections/{id}/margin/{symbol}` | Read current native settings |
| `POST /api/bots/preview` | Read-only preflight for `BotCreate` |
| `POST /api/bots` | Validate and save `BotCreate`; no trading command |
| `GET /api/bots` | Bots with PnL, allocations, editability, cycles, grid and turnover |
| `GET /api/bots/{id}` | Full bot view plus orders, fills, operations and margin-change evidence |
| `GET /api/bots/{id}/funding` | Native funding forecasts |
| `POST /api/bots/{id}/preview` | Read-only preflight for `BotUpdate` |
| `PUT /api/bots/{id}` | Validate/save full `BotUpdate`, enforcing ownership/editability |
| `POST /api/bots/{id}/commands` | Explicit `run`, `pause`, `close` or original-evidence `sync` |
| `DELETE /api/bots/{id}` | Delete eligible configuration/layout; retain trading history |
| `GET /api/operations/{id}` | Local operation evidence/status |
| `GET /api/alerts` | Recent retained alerts |
| `POST /api/alerts/{id}/acknowledge` | Mark an alert acknowledged locally |
| `GET /api/points` | Account-scoped point snapshots |
| `POST /api/points/refresh` | Read/collect implemented account points |
| `GET /api/connections/{id}/points/history?period=24h` | Stored point history; period is `24h`, `7d` or `30d` |
| `GET /api/notifications` | Whether Telegram is configured and station alerts are present |

Safe service inspection:

```bash
curl --fail http://127.0.0.1:8080/health
curl --fail http://127.0.0.1:8080/api/catalog
```

## Configuration shapes

`BotCreate` requires `name`, a unique `request_id` (8–80 characters), `strategy` and typed `parameters`. `BotUpdate` requires a name and the complete parameter object. Request models forbid extra fields. Decimal values should be sent as strings to preserve exact values.

A grid creation shape, with an existing connection ID substituted by the caller:

```json
{
  "name": "BTC grid",
  "request_id": "caller-unique-request-id",
  "strategy": "grid",
  "parameters": {
    "connection_id": "existing-connection-id",
    "symbol": "BTC",
    "direction": "long",
    "lower_price": "70000",
    "upper_price": "90000",
    "grid_count": 20,
    "open_position_on_start": false,
    "capital": {
      "investment_usd": "300",
      "leverage": 3,
      "margin_mode": "isolated"
    },
    "slippage_bps": "20"
  }
}
```

This illustrates structure, not suitable trading parameters for an account. Native precision, minimum orders, balance and reservations are validated against the selected account. `grid_count` and leverage require integers; neutral grids require an even count and `open_position_on_start=false`.

For `spread_hedging`, parameters are `long_connection_id`, `long_symbol`, `short_connection_id`, `short_symbol`, `threshold_pct`, `target_usd`, optional `slippage_bps`, optional `reopen_interval_seconds`, and `reopen_random_wait_seconds`. The two account IDs must differ. Tickers are independent, retain their native case/prefix and must exist in their selected venue’s active perpetual catalog. No asset-equivalence check is performed. Hedge previews return `long_quantity` and `short_quantity` separately. Intervals are 60–2,592,000 seconds and the random upper bound is 0–300 seconds.

`GET /api/connections/{id}/markets` returns the selected venue's active ticker list. Add `?refresh=true` to fetch it again rather than use the five-minute cache.

`ConnectionCreate` requires a name, provider and secret `api_private_key`. Arcus additionally requires address and account_index; Lighter requires account_index and api_key_index, with optional address; Entropy requires address and omits both numeric indices. Credentials are validated through native reads before storage. Do not put secret example values in documentation, test captures or issue reports.

A command body contains only an `action`, such as `{"action":"pause"}`. A returned bot state is not a promise that every background order has filled; inspect original operation/position evidence. Calls to `run` and `close` can lead to real native writes and must not be used for read-only health checks.

## Results and errors

Money and quantities in model responses are decimal strings. Unknown values remain JSON null or explicit unavailable/unsupported status. `holding` can describe an initialized flat grid; do not infer native positions from the lifecycle label. [Bot model](BOTS.md) explains allocations and lifecycle.

Request validation errors use HTTP 422 with location/message details. Domain validation uses HTTP 400 with `detail`; operation lookup can return HTTP 404. Transport/read failures do not imply an order was rejected. Preserve original IDs and inspect stored evidence rather than repeating an action based on HTTP status alone.

Pending native orders and margin settings block edits/deletion/new execution. Public order views omit encrypted prepared payloads; account views omit private configuration. No API response provides the encryption key.
