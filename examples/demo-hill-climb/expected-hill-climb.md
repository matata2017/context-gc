# Expected hill-climb outcome

`python scripts/analyze_patterns.py --target examples/demo-hill-climb --min-occurrences 2`

The demo seeds 10 patterns across 3 kinds. With min-occurrences=2, the analyzer should:

1. **Cluster scalar-sync patterns** (5 occurrences of `docker-compose.yml` ↔ `README.dirty.md`) → proposal `prop-scalar-sync-*` with type `add_scalar_sync_contract`
2. **Cluster memory-conflict patterns** (3 occurrences of `user-preference:verbosity`) → proposal `prop-memory-conflict-*` with type `add_memory_condense_contract`
3. **Not cluster** duplicate-block patterns (2 occurrences but different copy files) → no proposal

Each proposal includes:
- `id`, `kind`, `domain`, `occurrences`, `latest`, `sources`
- `action.type`, `action.description`, `action.suggested_so_md_entry`
- `status: "proposed"`

Applying a proposal via `--apply <id>`:
- Adds the suggested SOURCES.md entry (if domain doesn't already exist)
- Marks proposal as `applied`
- Writes audit record to decisions.jsonl
