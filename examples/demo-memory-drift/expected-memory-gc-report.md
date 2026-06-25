# Expected memory GC outcome

## MARK (read-only)

`python scripts/mark.py --target examples/demo-memory-drift` should surface, without editing:

- `MEMORY-SUPERSEDED-CHAIN` — three dated `user-preference` variants should compact to one current memory.
- `MEMORY-CONFLICT` / `PROFILE-DRIFT` — `memory/profile.md` (verbose) disagrees with the preference memories (concise); resolve by review, do not auto-overwrite.
- `MEMORY-LEAK` — append-only memory growth for the same subject.

## Minor GC report-only

`python scripts/minor_gc.py --target examples/demo-memory-drift` reports:

```
## REPORT_ONLY
- `user-verbosity-preference` `memory/current/user-preference.md`: would write current memory summary
```

## Minor GC apply-safe

`python scripts/minor_gc.py --target examples/demo-memory-drift --apply-safe` produces:

```
## AUTO_FIXED
- `user-verbosity-preference` `memory/current/user-preference.md`: CURRENT_MEMORY_WRITTEN
```

It writes `memory/current/user-preference.md` from the declared Root (`memory/user-preference-2026-03.md`),
lists every source file as Evidence, and does **not** delete the originals. The conflicting
`memory/profile.md` is not in the `memory-condense` contract, so it stays for human review rather than
being auto-resolved.

Safety:

- `memory-condense` runs only because `SOURCES.md` declares it and `.context-gc/config.yml` sets
  `memory_gc.enabled: true` plus `apply_safe: true`.
- Ambiguous conflicts within a contract are reported as `CONFLICT_NEEDS_REVIEW`, never auto-written.
- Originals are archived only when `memory_gc.allow_archive: true`.
