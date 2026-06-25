# Demo: memory drift cleanup

This fixture shows long/mid-term memory and a user profile drifting over time.

`memory/` holds three dated variants of one preference plus a profile copy. `SOURCES.md` declares a
`memory-condense` contract whose `Memory target` is `memory/current/user-preference.md`. Minor GC can
write a current canonical memory **only** when `memory_gc.enabled: true` and `apply_safe` is set, and
it never deletes the original evidence.

Run:

```bash
python scripts/mark.py --target examples/demo-memory-drift
python scripts/minor_gc.py --target examples/demo-memory-drift
python scripts/minor_gc.py --target examples/demo-memory-drift --apply-safe
```

The ambiguous-conflict variant (`memory/profile.md` says verbose, preferences say concise) is reported
as `CONFLICT_NEEDS_REVIEW` instead of being auto-resolved.
