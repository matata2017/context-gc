# Demo: review queue

This fixture shows how scattered "needs a human" findings become **one decision queue** that the
SKILL `review` flow turns into quick AskUserQuestion choices.

`.context-gc/findings.json` and `.context-gc/memory-gc.json` are pre-seeded (as `mark.py` /
`minor_gc.py` would emit them) with two open decisions: a memory verbosity conflict and an SDD drift.

Run:

```bash
python scripts/review_queue.py --target examples/demo-review-queue
```

`review_queue.py` aggregates them into `.context-gc/review-queue.json`. Each item carries a one-line
`summary`, `evidence`, labeled `options` (each with a declarative `action`), and a `recommend` index
(`-1` when genuinely ambiguous). The SKILL asks one question per item, then performs the chosen action
and updates `SOURCES.md`. The script itself decides nothing.
