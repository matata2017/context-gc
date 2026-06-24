# Drift authority map

## Entries

### `deployment-procedure` — how to deploy the demo app

- **Root:** `docs/deploy.md` (dedicated deployment documentation)
- **Owner:** `devops`
- **Risk:** `high` — stale deployment instructions can break releases
- **Copies:**
  - `README.md` — pointer only; must not restate full procedure
  - `wiki/export.md` — generated/exported copy; should be regenerated from root or marked derived
- **Re-check:** `grep -R "Deploy: run" README.md docs wiki`
- **Last verified:** YYYY-MM-DD
- **Last checked by:** context-gc
- **Status:** `UNKNOWN_ROOT` until the user confirms `docs/deploy.md` as root; then `SYNCED`
