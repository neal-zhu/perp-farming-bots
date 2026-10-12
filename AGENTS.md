# Repository instructions

## Independent implementation

- Do not copy, import, reference as a dependency, or transplant code, tests, fixtures, configuration, or internal documentation from the hedge-arb repository or other private trading projects.
- Implement from this repository’s public specifications and independently verified upstream documentation.
- Reuse public dependencies only after verifying their licenses, supported venue domains, and recovery behavior. Record provenance and required notices.

## Explicit truth

- Unknown order, fill, fee, balance, funding, or points states must remain explicit. Never substitute a zero or a guessed success.
- Do not add compatibility shims, silent fallback fields, or duplicate representations that conceal correctness problems.

## Trading authority

- No live trades, production credentials, automatic risk actions, or upstream service messages without direct user authorization.
- Preserve user-directed execution, durable recovery, and account-scoped isolation.
