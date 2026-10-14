# Security scope

The current application is a single-owner, local service. The UI and HTTP API have no authentication. Keep `PFB_HOST=127.0.0.1` for local Python execution and retain Compose's loopback port mapping. For a remote host, use an SSH tunnel as described in [Operations](docs/operations.md); exposing the port publicly is outside the supported setup.

Account API keys, signed requests and Telegram tokens are encrypted locally with the key in the data directory. This is local storage protection, not an access-control system. Anyone with the database and encryption key can decrypt saved secrets. Back up and protect both together; never attach either to an issue or commit them.

Routine tests use isolated credentials and native responses. Funded trades, wallet approvals, reward claims, permission changes and automatic risk trades are not authorized by contributing to the repository.

## Reporting

Report a suspected vulnerability privately to a repository maintainer before sharing exploitable details. If no private contact channel is available, open an issue requesting one without including the vulnerability details or sensitive data. For ordinary bugs, provide redacted logs and reproduction steps through the bug report template.
