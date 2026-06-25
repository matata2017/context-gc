# Hooks integration — make context-gc incremental

`context-gc` works best when it is not only a manual clean-up pass, but also a **write barrier**:
whenever docs/config/agent context changes, a hook records a dirty card; at the end of the session,
the agent reminds you to run a small incremental MARK pass.

Hooks must stay conservative:

- ✅ record risk / remind / block clearly unsafe sweeps
- ✅ optionally run quiet auto-MARK after a configured dirty-card threshold
- ❌ never auto-edit docs without a confirmed sweep plan
- ❌ never decide truth when roots conflict

## Hook roles

### 1. Dirty-card hook (PostToolUse)

After `Write`, `Edit`, or `MultiEdit`, inspect the changed path. If it touches a context-bearing file,
append an entry to `.context-gc/dirty.jsonl`.

Tracked by default:

- docs: `*.md`, `docs/**`, `README*`, `CHANGELOG*`
- config: `*.yaml`, `*.yml`, `*.json`, `.env.example`, `docker-compose*.yml`
- agent context: `CLAUDE.md`, `SOUL.md`, `skills/**/SKILL.md`, `memory/**`, `.claude/**`

This is the GC **card table**: next run checks only dirty cards first.

### 2. End-of-turn reminder (Stop)

At session stop, if `.context-gc/dirty.jsonl` exists, print a short reminder:

> context-gc: 5 context-bearing files changed. Run MARK to check drift and update SOURCES.md.

It does **not** run a sweep automatically.

### 3. Sweep guard (PreToolUse, optional but recommended)

Before writing many docs/config/agent files, block unless the prompt or tool input contains an
explicit sweep approval marker, such as:

```text
context-gc: sweep approved
```

Use this only in stricter teams. It prevents accidental "rewrite the docs" operations that collect
live content by mistake. The bundled helper implements this as:

```bash
python scripts/context_gc_hook.py sweep-guard
```

It denies high-risk context writes when:

- the tool is `MultiEdit` or `NotebookEdit` against a context-bearing file,
- more than one context-bearing file is written at once, or
- a root agent file such as `CLAUDE.md`, `SOUL.md`, or `SKILL.md` is edited.

To proceed, first show a MARK report and sweep plan, get explicit user approval, then retry the
write with `context-gc: sweep approved` present in the tool input.

## Claude Code example settings

Copy `examples/claude-settings-hooks.json` into your project `.claude/settings.json`. **Use an
absolute path to the script.** Hooks run from the target project's working directory, not from the
skill directory, so a relative `scripts/context_gc_hook.py` will not resolve once context-gc is
installed under `~/.claude/skills/`. Replace `ABSOLUTE_PATH_TO/context-gc` with the real install
path (for example `/home/you/.claude/skills/context-gc` or `D:/context-gc`).

The state files the hook writes (`.context-gc/dirty.jsonl`) are still created in the target project,
which is intended — dirty cards belong to the repo being edited.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python scripts/context_gc_hook.py sweep-guard"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python scripts/context_gc_hook.py dirty-card"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python scripts/context_gc_hook.py stop-reminder"
          }
        ]
      }
    ]
  }
}
```

### 4. Quiet auto-MARK (optional)

`dirty-card` can run a small read-only MARK after N context-bearing edits. This is disabled by
default and configured in `.context-gc/config.yml`:

```yaml
auto_mark:
  enabled: false
  threshold: 10
  mode: quiet
  max_seconds: 5
```

When enabled, the hook runs:

```bash
python scripts/mark.py --target . --dirty-only --report-out .context-gc/last-auto-mark.md --json-only
```

It writes candidates under `.context-gc/` and resets the dirty counter after success. It never runs
SWEEP, never rewrites facts, and never decides authority.

### 5. Preventive Minor GC for automated agents (optional)

Minor GC is for autonomous runs where you want drift prevention with minimal human interruption:

> **Minor GC = quiet MARK + pre-authorized safe fixers.**

It runs only on dirty `SOURCES.md` domains. It may apply low-risk fixes only when a domain declares an
`Auto-fix` contract and config enables `minor_gc.apply_safe`:

```yaml
minor_gc:
  enabled: false
  interval_dirty_cards: 10
  interval_turns: 10
  apply_safe: false
  max_files_per_run: 3
  max_seconds: 5
  allow_fixers:
    - "scalar-sync"
    - "pointer-copy"
    - "generated-state-cleanup"
  protected:
    - "CLAUDE.md"
    - "SOUL.md"
    - "memory/**"
    - "skills/**/SKILL.md"
    - "docs/adr/**"
    - "docs/sdd/**"
```

The hook subcommand is:

```bash
python scripts/context_gc_hook.py minor-gc
```

`Stop` also increments the minor-GC turn counter and may run it when thresholds are reached. Minor GC
writes `.context-gc/minor-gc-report.md` and `.context-gc/minor-gc.json`. It skips protected,
`UNKNOWN_ROOT`, `FORK`, and `HISTORICAL` domains.

### 6. CI scanners (optional remote gate)

Use hooks as the local write barrier, and CI as the remote gate. Do not reimplement mature tools; call them when present:

- `lychee` for link rot and broken anchors.
- `markdownlint` for Markdown structure and consistency.
- `Vale` for prose style, terminology, and project writing rules.
- Project-specific scripts for config/doc drift (for example, compare documented ports with compose files).

Treat scanner output as MARK evidence. Only auto-fix mechanical formatting; do not auto-rewrite facts without a sweep plan.



Claude Code passes hook event JSON on stdin. The script is deliberately defensive and supports
several common shapes:

- `tool_input.file_path`
- `tool_input.path`
- `tool_input.notebook_path`
- `tool_input.files[].path`
- top-level `file_path` / `path`

If no path can be found, the hook exits 0 and does nothing.

Verify the helper after installation:

```bash
python scripts/context_gc_hook.py --self-test
```

## Recommended workflow

1. Work normally.
2. Hooks collect dirty cards as context files change.
3. At the end, Stop hook reminds you.
4. Run context-gc MARK against dirty files first.
5. Confirm SWEEP plan before any edits.
6. Update `SOURCES.md` as the write barrier.
