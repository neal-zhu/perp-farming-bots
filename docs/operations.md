# Operations

## Start and configure

Run one application process per data directory. The default Python process listens on `127.0.0.1:8080`. Compose binds the host port to `127.0.0.1:8080` and stores state in the named `bot-data` volume. Docker's internal `0.0.0.0` binding does not change that host mapping.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PFB_HOST` | `127.0.0.1` | Listen address for Python execution |
| `PFB_PORT` | `8080` | Listen port |
| `PFB_DATA_DIR` | `data` | Database, encryption key and instance lock directory |
| `PFB_TIMEZONE` | `Asia/Shanghai` | Timestamps displayed by the UI |

To select a port:

```bash
PFB_PORT=8090 uv run perp-farming-bots
```

The application does not automatically load `.env`. Copy [.env.example](../.env.example), edit it, then explicitly load it:

```bash
uv run --env-file .env perp-farming-bots
```

The Compose file uses its checked-in defaults; it does not automatically forward arbitrary `PFB_*` variables from `.env` into the container. The published Compose port and Docker healthcheck currently use 8080.

## Remote server access

There is no application authentication. Keep the service bound to localhost on the server and use an SSH tunnel:

```bash
ssh -N -L 8080:127.0.0.1:8080 user@server
```

Open http://127.0.0.1:8080 on your own computer. Use a different local port if 8080 is already occupied. Public port exposure is outside the supported setup; see [security scope](../SECURITY.md).

## Linux service with systemd

The [service unit](../deploy/perp-farming-bots.service) runs under the existing `ubuntu` user, from `/opt/perp-farming-bots`, with private state in `/var/lib/perp-farming-bots`. It listens on `127.0.0.1:8080`, starts at boot and restarts after a process failure. Install Git and [uv](https://docs.astral.sh/uv/getting-started/installation/) first. If your server uses another account, edit the unit's `User` and `Group` and use that owner when creating the checkout.

For a new installation, run as `ubuntu`:

```bash
sudo install -d -m 755 -o ubuntu -g ubuntu /opt/perp-farming-bots
git clone https://github.com/neal-zhu/perp-farming-bots.git /opt/perp-farming-bots
cd /opt/perp-farming-bots
uv sync --frozen --no-dev --python 3.12
sudo install -m 644 deploy/perp-farming-bots.service /etc/systemd/system/perp-farming-bots.service
sudo systemctl daemon-reload
sudo systemctl enable --now perp-farming-bots
```

Do not clone over an existing installation. For an existing data directory, restore its database and matching encryption key before starting the service. The service invokes the installed executable directly, without downloading dependencies on restart. Use the SSH tunnel above to access it.

```bash
sudo systemctl status --no-pager perp-farming-bots
sudo journalctl -u perp-farming-bots -n 100 --no-pager
sudo systemctl stop perp-farming-bots
sudo systemctl restart perp-farming-bots
```

Before an update, stop this service, back up `/var/lib/perp-farming-bots`, update the checkout and run `uv sync --frozen --no-dev --python 3.12`, then restart. Keep the original service user so the same private data directory remains readable.

## Move an existing instance to another host

Prepare the destination's code and dependencies without starting its application. Use code matching the source database schema. Then:

1. Gracefully stop the source application and verify that its process has exited. Keep it stopped throughout the move.
2. Back up the source data directory privately. Transfer the database and its matching `encryption.key` together over SSH. Preserve all bot, inventory, journal and history records; use SQLite's backup API if exporting the database separately.
3. Place the files in the destination's configured data directory, owned by its service user, with directory mode `700` and file mode `600`. Preserve any existing destination data separately before restoring. Verify the transferred files and database integrity before startup.
4. Start only the destination instance, then inspect health, account connectivity and bot state. Healthy active bots resume their existing authority; interrupted operations retain the original-order recovery rules.

Never run both hosts against copies of the same trading state. A rollback also requires stopping the destination first and carrying its latest database and matching key back, so confirmed trades and recovery evidence are not lost.

## Health and logs

```bash
curl --fail http://127.0.0.1:8080/health
docker compose logs --tail=100 app
```

For Python execution, logs go to the terminal unless the operator redirects them. `/health` reports HTTP service state, native execution mode, `last_tick` and `loop_alive`. A successful HTTP response alone does not certify venue connectivity, account authorization or a confirmed order; inspect bot/account state as well.

| Symptom | Check |
| --- | --- |
| Cannot open the page | Process running, configured host/port, port collision and SSH tunnel |
| Another instance uses the directory | Stop the existing process; the file lock is released when it exits |
| Connection retries | Keep the host awake and online; inspect retained error type and HTTP status |
| Bot paused after prolonged outage | Check connectivity, then explicitly Run to resume |
| Order/position unknown | Query original orders and compare native inventory; do not erase the journal or resend |
| Unsupported schema | Stop and preserve the directory; use code matching the data format or a separate empty directory |

GET reads and Entropy's read-only POST `/info` can retry once for transport/gateway failures within a 20-second budget. Signed writes are sent once. Active-strategy read failures pause after five continuous minutes; the outage timer is process-local and restarts with the service. Historical alerts remain until acknowledged, even after recovery.

## Stop, restart and update

Closing the browser does not stop the background strategy. Graceful service shutdown stops monitoring and does not close exchange positions.

For Python execution, stop the foreground process with Ctrl+C. For Compose:

```bash
docker compose stop
```

Healthy active bots retain their user-selected authority on restart. Interrupted or unknown operations are queried by their original identities and require review before new execution. Manually paused bots remain paused. An update is therefore not a trading pause; if you want no automatic strategy actions after restart, pause the bots first through the UI.

Before updating, stop the process and back up its data. Review [exchange scope](exchanges.md) and configuration/storage changes before switching versions. Then, from the checkout:

```bash
git pull --ff-only
uv sync --frozen
uv run perp-farming-bots
```

For Docker, rebuild after stopping and backing up the volume:

```bash
docker compose up --build -d
```

Current storage uses **SQLite schema 10**. The application rejects unsupported versions and does not silently convert old bot configurations. Do not delete funded inventory or recovery evidence to bypass this check.

## Back up and restore

The data directory contains:

| File | Purpose |
| --- | --- |
| `app.live.db` | Account metadata, encrypted credentials, bot configuration, inventory, order/operation evidence, points samples and settings |
| `encryption.key` | Local Fernet key used to decrypt saved credentials, signed requests and notification tokens |
| `instance.lock` | Single-process file lock; it is not an encryption key |

With the process stopped, copy the entire directory to a private backup location. For the default local directory:

```bash
cp -a data data-backup
```

For Compose, stop the service and export its data to a local private directory:

```bash
mkdir -m 700 backup
docker compose run --rm --no-deps -T --entrypoint tar app -C /app/data -cf - . > backup/data.tar
chmod 600 backup/data.tar
```

Restore the database and the matching encryption key together while no process is using the target directory. For local Python execution, point `PFB_DATA_DIR` at the restored directory. For the Compose volume:

```bash
docker compose run --rm --no-deps -T --entrypoint tar app -C /app/data -xf - < backup/data.tar
```

Start only one instance, inspect interrupted operations and native inventory, and follow the bot's recovery state. `docker compose down` preserves the volume; `docker compose down --volumes` deletes it. Keep backups, environment files and account screenshots out of Git and public issues.
