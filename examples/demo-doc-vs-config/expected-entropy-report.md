# Expected entropy report — doc vs config drift

## Entropy report — examples/demo-doc-vs-config

Status legend: SYNCED | DRIFTED | NOT_CHECKED | FORK | UNKNOWN_ROOT

🔴 CONTRADICTION  DRIFTED  README.md:3  "Start the API at http://localhost:8000"  ↔  root docker-compose.yml:4 "8080:8080"  → reconcile

## Why

The README states the public API port as 8000, but the live compose configuration maps the service to 8080. For this fact domain, `docker-compose.yml` is the likely root because it controls the runtime mapping.

## Sweep plan — apply? (y/n)

- `README.md`: change `http://localhost:8000` to `http://localhost:8080`.
- `SOURCES.md`: add a `service-api-port` entry with `docker-compose.yml` as Root and `README.md` as Copy.
