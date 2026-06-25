# Drift authority map

## Entries

### `service-api-port` — local API port shown in README

- **Root:** `docker-compose.yml`
- **Copies:**
  - `README.dirty.md` — documents the local port
- **Auto-fix:** `scalar-sync`
- **Root extract:** `"(\d+):\1"`
- **Copy replace:** `localhost:(\d+)`
- **Protected:** `false`
- **Status:** `SYNCED`
