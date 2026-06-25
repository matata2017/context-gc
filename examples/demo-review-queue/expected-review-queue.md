# Expected review-queue outcome

`python scripts/review_queue.py --target examples/demo-review-queue` aggregates the two pre-seeded
open findings into `.context-gc/review-queue.json` with `"open": 2`.

## Item 1 — memory-conflict

- `summary`: memory subject `user-preference` has conflicting cues `concise` and `verbose`
- `evidence`: `memory/preference.md`, `memory/profile.md`
- `options`:
  1. Keep `memory/preference.md` as current → `action: set_current_memory`
  2. Keep `memory/profile.md` as current → `action: set_current_memory`
  3. Both — scope by context (FORK) → `action: mark_fork`
- `recommend`: -1 (genuinely ambiguous — present neutrally)

## Item 2 — sdd-drift

- `summary`: `docs/sdd.md` says password login; code uses OAuth device flow
- `evidence`: `docs/sdd.md:5`
- `options`:
  1. Update doc to match code/tests → `action: reconcile_to_root`
  2. Code is incomplete — keep spec, flag gap → `action: flag_implementation_gap`
  3. Doc is historical — preserve → `action: mark_historical`
- `recommend`: -1

## SKILL `review` flow

For each open item the SKILL asks one AskUserQuestion built from `summary` + `evidence` + `options`,
performs the chosen declarative `action`, updates `SOURCES.md`, and removes the item. The script
decides nothing and edits no project files.
