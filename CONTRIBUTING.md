# Contributing

Thanks for improving `context-gc`. Keep contributions focused on the Claude Code skill, its hook
helpers, eval fixtures, and documentation needed to operate them.

## Local checks

Run these before opening a pull request:

```bash
python scripts/validate_context_gc.py
python scripts/run_evals.py
```

If you change hook behavior, also run:

```bash
python scripts/context_gc_hook.py --self-test
```

## Change rules

- Update `SOURCES.md` when a root→copy relationship changes.
- Add or update an eval fixture when changing MARK/SWEEP/BARRIER behavior.
- Do not auto-sweep user content in hooks. Hooks may guard, record dirty cards, and remind.
- Keep `SKILL.md` concise. Put detailed guidance in `references/` and load it progressively.

## Pull request checklist

- The change preserves the MARK → SWEEP → BARRIER flow.
- Destructive edits remain behind explicit user confirmation.
- New drift categories include expected report examples.
- Validation commands pass locally.
