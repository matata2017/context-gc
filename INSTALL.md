# Installation

`context-gc` is a Claude Skill. Install it by copying this repository directory into a Claude skills location, or by packaging it as a `.skill` file when your environment provides a skill packaging command.

## Option A — use as a local skill directory

Copy the folder into your Claude skills directory:

```text
~/.claude/skills/context-gc/
```

On Windows:

```powershell
Copy-Item -Recurse D:\context-gc C:\Users\<you>\.claude\skills\context-gc
```

Then reload skills in Claude Code:

```text
/reload-skills
```

Use prompts like:

```text
Run context-gc on docs and configs. The README and docker-compose seem to disagree.
```

## Option B — keep it as a standalone repo

You can also keep `context-gc` as a standalone Git repo and reference it while developing or testing:

```text
Skill path: /path/to/context-gc
Task: Run MARK on examples/demo-doc-vs-config and compare against expected-entropy-report.md
```

This is useful for contributors.

## Try the demos

```bash
python scripts/validate_context_gc.py
```

Then inspect:

- `examples/demo-doc-vs-config/`
- `examples/demo-agent-context-rot/`
- `examples/demo-kb-duplication/`

Each demo has intentionally rotten input files and an expected report.

## Optional hooks

Copy `examples/claude-settings-hooks.json` into your project `.claude/settings.json`, then adjust paths if needed.

Hooks do two things:

1. `PostToolUse` records context-bearing edits into `.context-gc/dirty.jsonl`.
2. `Stop` reminds you to run MARK before drift accumulates.

Hooks never auto-sweep. They only record dirty cards and remind.

## CI

This repo includes `.github/workflows/validate.yml`:

- runs `python scripts/validate_context_gc.py`
- checks `evals/evals.json` parses
- optionally runs `lychee` link checking as a non-blocking job

The link-check job is `continue-on-error: true` because external sites can be flaky. Treat failures as MARK evidence, not automatic release blockers.
