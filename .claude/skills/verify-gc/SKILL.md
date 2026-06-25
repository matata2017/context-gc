---
name: verify-gc
description: Run the context-gc verification trifecta — structural validator, eval fixture checker, hook self-test. Use after edits to any script, demo, or eval.
---

Run all three and report any failure clearly:

```bash
python scripts/validate_context_gc.py
python scripts/run_evals.py
python scripts/context_gc_hook.py --self-test
```

If any command fails, describe the failure and suggest which file to inspect first. If all pass,
confirm and remind that `gc_tick.py --target . --quiet` runs a full governance tick.
