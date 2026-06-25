# Demo: preventive Minor GC

This fixture shows a pre-authorized low-risk fix: `SOURCES.md` declares `docker-compose.yml` as the root for the local API port and allows `scalar-sync` to update `README.md`.

Run:

```bash
python scripts/minor_gc.py --target examples/demo-minor-gc
python scripts/minor_gc.py --target examples/demo-minor-gc --apply-safe
```

Minor GC should auto-fix only the declared scalar copy. Protected or unknown-root domains stay report-only.
