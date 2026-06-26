# Drift authority map

This file records the root set for this repository. `context-gc` reads it as the write barrier:
when a root or copy changes, re-check the declared relationship before publishing.

## Entries

### `skill-protocol` — core Claude Code skill workflow

- **Root:** `SKILL.md` (the Claude Code skill entrypoint and behavioral contract)
- **Owner:** maintainer
- **Risk:** high — stale workflow text changes how Claude collects context garbage
- **Copies:**
  - `README.md` — public summary; must match the three-phase MARK/SWEEP/BARRIER contract
  - `README.zh-CN.md` — Chinese README; must stay in sync with README.md
  - `research/context-gc-research.md` — rationale; may expand the model but must not contradict the contract
- **Re-check:** `python scripts/validate_context_gc.py`
- **Last verified:** 2026-06-26
- **Last checked by:** Claude
- **Status:** `SYNCED`

---

### `hook-behavior` — Claude Code dirty-card, reminders, guard, auto-MARK, minor GC, review nudge

- **Root:** `scripts/context_gc_hook.py` (executable hook behavior)
- **Owner:** maintainer
- **Risk:** high — stale hook docs can create false confidence about enforcement
- **Copies:**
  - `references/hooks.md` — detailed hook guide; must match implemented subcommands
  - `examples/claude-settings-hooks.json` — copy-paste Claude Code settings; must call valid subcommands
  - `INSTALL.md` — install guidance; must not advertise unavailable hook behavior
- **Re-check:** `python scripts/context_gc_hook.py --self-test`
- **Last verified:** 2026-06-25
- **Last checked by:** Claude
- **Status:** `SYNCED`

---

### `runner-scripts` — the deterministic Python runners

- **Root:** `scripts/` (the executable runners that detect/condense/aggregate drift)
- **Owner:** maintainer
- **Risk:** high — a runner referenced in docs but missing breaks the managed flow
- **Copies:**
  - `README.md` — the Files tree must list every `scripts/*.py` runner accurately
  - `SKILL.md` — workflows must only call subcommands/flags the runners implement
- **Re-check:** `python scripts/validate_context_gc.py` (asserts every runner is referenced)
- **Last verified:** 2026-06-25
- **Last checked by:** Claude
- **Status:** `SYNCED`

---

### `eval-fixtures` — demo scenarios and expected reports

- **Root:** `evals/evals.json` (machine-readable eval scenario list)
- **Owner:** maintainer
- **Risk:** medium — stale demos weaken user trust but do not alter hook behavior
- **Copies:**
  - `examples/demo-doc-vs-config/expected-entropy-report.md` — must cover doc/config drift
  - `examples/demo-sdd-drift/expected-entropy-report.md` — must cover SDD/spec drift after requirement changes
  - `examples/demo-agent-context-rot/expected-entropy-report.md` — must cover agent context rot
  - `examples/demo-agent-drift-advanced/expected-entropy-report.md` — must cover semantic/memory/skill/tone/session drift
  - `examples/demo-kb-duplication/expected-entropy-report.md` — must cover duplication/compaction
  - `examples/demo-minor-gc/expected-minor-gc-report.md` — must cover pre-authorized safe auto-fix
  - `examples/demo-memory-drift/expected-memory-gc-report.md` — must cover memory-condense + conflict review
  - `examples/demo-review-queue/expected-review-queue.md` — must cover the review-queue aggregation
	  - `examples/demo-agent-autonomy/expected-tick.md` — must cover agent self-resolve within autonomy policy
      - `examples/demo-hill-climb/expected-hill-climb.md` — must cover the hill-climb pattern analysis
- **Re-check:** `python scripts/run_evals.py`
- **Last verified:** 2026-06-25
- **Last checked by:** Claude
- **Status:** `SYNCED`

---

### `github-release-readiness` — open-source repository metadata

- **Root:** `.github/` (GitHub workflows, issue templates, and PR template)
- **Owner:** maintainer
- **Risk:** low — metadata drift affects contribution quality, not runtime behavior
- **Copies:**
  - `README.md` — must describe validation commands and contribution entrypoints accurately
  - `CONTRIBUTING.md` — must match the local validation commands
- **Re-check:** `python scripts/validate_context_gc.py && python scripts/run_evals.py`
- **Last verified:** 2026-06-24
- **Last checked by:** Codex
- **Status:** `SYNCED`

---

### `project-agent-instructions` — how Claude works in THIS repo

- **Root:** `CLAUDE.md` (project instructions loaded into every Claude Code session here)
- **Owner:** maintainer
- **Risk:** medium — stale instructions change how the agent treats this repo (commands, safety rules)
- **Copies:** (none — this is a root-only authority; if its rules get echoed elsewhere, declare them here)
- **Re-check:** `python scripts/validate_context_gc.py`
- **Last verified:** 2026-06-26
- **Last checked by:** Claude (surfaced by context-gc's own coverage-gap check)
- **Status:** `SYNCED`

---

### `install-flow` — how users/agents install and bootstrap context-gc

- **Root:** `scripts/init_context_gc.py` (the actual install/bootstrap behavior — CLI flags, what it writes)
- **Owner:** maintainer
- **Risk:** medium — if these docs advertise a wrong command/flag/URL, install fails for new users
- **Copies:**
  - `INSTALL.md` — full install guide; commands must match init's real flags
  - `INSTALL_AGENT.md` — the paste-to-agent install snippet; its `init` command must stay valid
  - `install.py` — one-command installer; repo URL + init invocation must be current
  - `scripts/install.sh` — Linux/macOS installer; same
  - `scripts/install.ps1` — Windows installer; same
- **Re-check:** `python scripts/init_context_gc.py --help` (compare flags against what the docs claim)
- **Last verified:** 2026-06-26
- **Last checked by:** Claude (surfaced by context-gc's own coverage-gap check)
- **Status:** `SYNCED`
