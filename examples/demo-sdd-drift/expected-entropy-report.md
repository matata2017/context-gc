# Expected entropy report — SDD drift

## Entropy report — examples/demo-sdd-drift

Status legend: SYNCED | DRIFTED | NOT_CHECKED | FORK | HISTORICAL | UNKNOWN_ROOT

🟠 SPEC_DRIFT  UNKNOWN_ROOT  docs/sdd.md:5-6  "Users authenticate with an email and password form"  ↔  code/tests src/auth_flow.py:1 and tests/test_auth_flow.py:5 use `oauth_device_flow`  → decide root

## Why

This is not just stale documentation. The SDD was once intended to describe the system, but current
implementation and tests now encode OAuth device flow. Before SWEEP, decide whether:

- `src/auth_flow.py` and `tests/test_auth_flow.py` are the current truth, so `docs/sdd.md` should be
  updated from password flow to OAuth device flow.
- `docs/sdd.md` still represents desired product intent, so code/tests are implementation drift and
  should be changed later.
- the password-flow text is historical and should be moved or marked `HISTORICAL`.

## Sweep plan — apply? (y/n)

- If code/tests are root: update `docs/sdd.md` current behavior to OAuth device flow and move password login to historical notes only if useful.
- If SDD is root: leave `docs/sdd.md` unchanged and create an implementation gap for `src/auth_flow.py` and tests.
- `SOURCES.md`: add an `auth-flow-current-behavior` entry with the confirmed root and derived copies.
