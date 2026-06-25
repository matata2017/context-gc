# Demo: SDD drift after requirement changes

This fixture shows an SDD that was true when written, but implementation moved after requirement
changes.

- `docs/sdd.md` still says the current auth flow is password login.
- `src/auth_flow.py` and `tests/test_auth_flow.py` show the implemented current flow is OAuth device
  flow.

Run context-gc MARK on this directory. It should flag `SPEC_DRIFT` and ask whether the SDD should
update to the code or the code should be brought back to the spec if product intent says otherwise.
