# Drift authority map

## Entries

### `service-api-port` — API port exposed for local development

- **Root:** `docker-compose.yml` (runtime port mapping)
- **Owner:** `platform/devex`
- **Risk:** `medium` — wrong port breaks local setup and onboarding
- **Copies:**
  - `README.md` — must match root
- **Re-check:** `grep -n "ports:" -A 2 docker-compose.yml && grep -n "localhost:" README.md`
- **Last verified:** YYYY-MM-DD
- **Last checked by:** context-gc
- **Status:** `SYNCED`
