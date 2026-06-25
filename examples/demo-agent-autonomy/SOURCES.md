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
- **Last verified:** 2026-06-25
- **Status:** `SYNCED`

---

### `user-verbosity-preference` — agent memory conflict

- **Root:** `memory/preference-concise.md`
- **Copies:**
  - `memory/profile-verbose.md` — conflicting profile memory
- **Auto-fix:** `memory-condense`
- **Memory subject:** `user-preference:verbosity`
- **Memory target:** `memory/current/verbosity.md`
- **Protected:** `true`
- **Status:** `SYNCED`
