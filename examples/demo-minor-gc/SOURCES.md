# Drift authority map

## Entries

### `service-api-port` — local API port shown in README

- **Root:** `docker-compose.yml` (compose controls the local API mapping)
- **Owner:** maintainer
- **Risk:** low — wrong local URL wastes developer time
- **Copies:**
  - `README.dirty.md` — documents the local API URL
- **Auto-fix:** `scalar-sync`
- **Root extract:** `"(\d+):\1"`
- **Copy replace:** `localhost:(\d+)`
- **Protected:** `false`
- **Re-check:** `python scripts/minor_gc.py --target .`
- **Last verified:** YYYY-MM-DD
- **Status:** `SYNCED`

---

### `agent-policy` — protected agent policy example

- **Root:** `CLAUDE.md`
- **Copies:**
  - `SOUL.md` — must be reviewed manually
- **Auto-fix:** `scalar-sync`
- **Root extract:** `(\d+) req/s`
- **Copy replace:** `\d+ req/s`
- **Protected:** `true`
- **Status:** `UNKNOWN_ROOT`
