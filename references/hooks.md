# Hooks integration — make context-gc incremental

`context-gc` works best when it is not only a manual clean-up pass, but also a **write barrier**:
whenever docs/config/agent context changes, a hook records a dirty card; at the end of the session,
the agent reminds you to run a small incremental MARK pass.

Hooks must stay conservative:

- ✅ record risk / remind / block clearly unsafe sweeps
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

### 3. Sweep guard (PreToolUse, optional)

Before writing many docs/config/agent files, block unless the prompt or tool input contains an
explicit sweep approval marker, such as:

```text
context-gc: sweep approved
```

Use this only in stricter teams. It prevents accidental "rewrite the docs" operations that collect
live content by mistake.

## Claude Code example settings

Copy `examples/claude-settings-hooks.json` into your project `.claude/settings.json` and adjust the
paths if needed.

```json
{
  "hooks": {
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

## Hook event assumptions

Claude Code passes hook event JSON on stdin. The script is deliberately defensive and supports
several common shapes:

- `tool_input.file_path`
- `tool_input.path`
- `tool_input.notebook_path`
- `tool_input.files[].path`
- top-level `file_path` / `path`

If no path can be found, the hook exits 0 and does nothing.

## Recommended workflow

1. Work normally.
2. Hooks collect dirty cards as context files change.
3. At the end, Stop hook reminds you.
4. Run context-gc MARK against dirty files first.
5. Confirm SWEEP plan before any edits.
6. Update `SOURCES.md` as the write barrier.
