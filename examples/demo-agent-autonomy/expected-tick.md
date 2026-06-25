# Expected autonomy demo tick outcome

`python scripts/gc_tick.py --target examples/demo-agent-autonomy` should:

1. **Minor GC** auto-fixes `README.dirty.md` from 8000 → 8080 via `scalar-sync`.
2. **Review queue** gets one `memory-conflict` item (concise vs verbose).
3. **Resolve --auto** leaves the memory-conflict open because memory-condense is in `never_auto`.
4. **TickResult** reports:
   - `auto_fixed: 1`
   - `agent_resolved: 0`
   - `escalated: 1`
   - `pending: 1`
   - `policy_level: assist`
5. `.context-gc/decisions.jsonl` contains no entries (nothing agent-resolved).
