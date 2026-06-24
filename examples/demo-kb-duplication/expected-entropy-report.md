# Expected entropy report — knowledge base duplication

## Entropy report — examples/demo-kb-duplication

Status legend: SYNCED | DRIFTED | NOT_CHECKED | FORK | UNKNOWN_ROOT

🟡 DUPLICATE  UNKNOWN_ROOT  deployment instructions are repeated in README.md, docs/deploy.md, and wiki/export.md  → compact → choose root

## Why

All three copies currently agree, so this is not yet a contradiction. It is still garbage-in-waiting: any future edit to only one copy creates drift. This is a drift factory.

## Sweep plan — apply? (y/n)

- Choose one root, likely `docs/deploy.md`, because it is the dedicated deployment document.
- Replace the deployment restatement in `README.md` with a pointer to `docs/deploy.md`.
- Replace the wiki export copy with a pointer or mark it as generated/derived.
- Add `deployment-procedure` to `SOURCES.md`.
