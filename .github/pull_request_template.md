## Summary

<!-- What changed and why? -->

## context-gc checklist

- [ ] Preserves MARK → SWEEP → BARRIER behavior.
- [ ] Keeps destructive SWEEP actions behind explicit approval.
- [ ] Updates `SOURCES.md` if authority-map relationships changed.
- [ ] Adds or updates eval/demo coverage when behavior changed.
- [ ] Runs:
  - [ ] `python scripts/validate_context_gc.py`
  - [ ] `python scripts/run_evals.py`

## Notes for reviewers

<!-- Call out ambiguous roots, intentional forks, or residual risk. -->
