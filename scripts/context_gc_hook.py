#!/usr/bin/env python3
"""context-gc hook helper.

Subcommands:
  dirty-card     Read Claude Code hook JSON from stdin; if a context-bearing path changed,
                 append a dirty card to .context-gc/dirty.jsonl.
  sweep-guard    Read PreToolUse JSON from stdin; deny broad context-bearing writes unless
                 the tool input includes the approval marker.
  stop-reminder  Print a short reminder if dirty cards exist.
  clear          Clear dirty cards after a successful MARK/SWEEP/BARRIER run.
  --self-test    Run local parser and guard checks.

The script is intentionally conservative: it never edits project files except its own
.context-gc/dirty.jsonl state file.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time
from typing import Any, Iterable

STATE_DIR = pathlib.Path(".context-gc")
DIRTY = STATE_DIR / "dirty.jsonl"
STATE = STATE_DIR / "state.json"
CONFIG = STATE_DIR / "config.yml"
LAST_AUTO_MARK = STATE_DIR / "last-auto-mark.md"
REVIEW_QUEUE = STATE_DIR / "review-queue.json"

CONTEXT_NAMES = {
    "README",
    "README.md",
    "CHANGELOG",
    "CHANGELOG.md",
    "CLAUDE.md",
    "SOUL.md",
    "SKILL.md",
}
CONTEXT_SUFFIXES = {".md", ".mdx", ".yaml", ".yml", ".json", ".toml", ".ini"}
CONTEXT_PARTS = {"docs", "documentation", "wiki", "memory", "skills", ".claude"}
CONFIG_NAMES = {"docker-compose.yml", "docker-compose.yaml", ".env.example"}
APPROVAL_MARKER = "context-gc: sweep approved"


def _read_raw_event() -> tuple[str, dict[str, Any]]:
    raw = sys.stdin.read().strip()
    if not raw:
        return "", {}
    try:
        return raw, json.loads(raw)
    except json.JSONDecodeError:
        return raw, {}


def _read_event() -> dict[str, Any]:
    return _read_raw_event()[1]


def _walk_paths(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key in ("file_path", "path", "notebook_path", "localPath"):
            v = value.get(key)
            if isinstance(v, str):
                yield v
        for key in ("files", "edits"):
            v = value.get(key)
            if isinstance(v, list):
                for item in v:
                    yield from _walk_paths(item)
        for key in ("tool_input", "input", "params", "parameters"):
            if key in value:
                yield from _walk_paths(value[key])
    elif isinstance(value, list):
        for item in value:
            yield from _walk_paths(item)


def _is_context_path(path: str) -> bool:
    p = pathlib.PurePath(path.replace("\\", "/"))
    name = p.name
    parts = set(p.parts)
    if name in CONTEXT_NAMES or name in CONFIG_NAMES:
        return True
    if p.suffix.lower() in CONTEXT_SUFFIXES and (parts & CONTEXT_PARTS):
        return True
    if p.suffix.lower() == ".md":
        return True
    return False


def _load_state() -> dict[str, Any]:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_section_config(section_name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(defaults)
    if not CONFIG.exists():
        return cfg
    lines = CONFIG.read_text(encoding="utf-8").splitlines()
    in_section = False
    list_key = None
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith(f"{section_name}:"):
            in_section = True
            list_key = None
            continue
        if in_section:
            if stripped and not raw.startswith(" "):
                break
            if stripped.startswith("- ") and list_key:
                cfg.setdefault(list_key, []).append(stripped[2:].strip().strip('"'))
                continue
            if ":" not in stripped:
                continue
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip().split("#", 1)[0].strip().strip('"')
            list_key = None
            if key in {"allow_fixers", "protected"}:
                cfg[key] = []
                list_key = key
            elif key in {"enabled", "apply_safe", "require_clean_git"}:
                cfg[key] = val.lower() == "true"
            elif key in {"threshold", "max_seconds", "interval_dirty_cards", "interval_turns", "max_files_per_run"}:
                try:
                    cfg[key] = int(val)
                except ValueError:
                    pass
            elif val:
                cfg[key] = val
    return cfg


def _load_auto_mark_config() -> dict[str, Any]:
    return _load_section_config("auto_mark", {"enabled": False, "threshold": 10, "mode": "quiet", "max_seconds": 5})


def _load_minor_gc_config() -> dict[str, Any]:
    return _load_section_config("minor_gc", {
        "enabled": False,
        "interval_dirty_cards": 10,
        "interval_turns": 10,
        "apply_safe": False,
        "max_files_per_run": 3,
        "max_seconds": 5,
        "mode": "conservative",
    })


    script = pathlib.Path(__file__).resolve().parent / "mark.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--target", ".", "--dirty-only", "--report-out", str(LAST_AUTO_MARK), "--json-only"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(1, int(cfg.get("max_seconds", 5))),
            check=False,
        )
        state = _load_state()
        state["last_auto_mark_rc"] = proc.returncode
        state["last_auto_mark_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        state["dirty_count_since_mark"] = 0 if proc.returncode == 0 else state.get("dirty_count_since_mark", 0)
        _save_state(state)
        if cfg.get("mode") != "silent":
            print("context-gc: quiet auto-MARK wrote .context-gc/last-auto-mark.md", file=sys.stderr)
    except Exception as exc:
        state = _load_state()
        state["last_auto_mark_error"] = str(exc)
        _save_state(state)


def dirty_card() -> int:
    event = _read_event()
    paths = sorted(set(_walk_paths(event)))
    hits = [p for p in paths if _is_context_path(p)]
    if not hits:
        return 0
    STATE_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    tool = event.get("tool_name") or event.get("tool") or event.get("name") or "unknown"
    with DIRTY.open("a", encoding="utf-8") as f:
        for path in hits:
            rec = {"ts": ts, "tool": tool, "path": path}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    state = _load_state()
    state["dirty_count_since_mark"] = int(state.get("dirty_count_since_mark", 0)) + len(hits)
    state["dirty_count_since_minor_gc"] = int(state.get("dirty_count_since_minor_gc", 0)) + len(hits)
    _save_state(state)

    cfg = _load_auto_mark_config()
    if cfg.get("enabled") and state["dirty_count_since_mark"] >= int(cfg.get("threshold", 10)):
        _run_auto_mark(cfg)
    else:
        print(f"context-gc: marked {len(hits)} dirty context file(s)", file=sys.stderr)
    return 0


    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _run_minor_gc(cfg: dict[str, Any]) -> int:
    script = pathlib.Path(__file__).resolve().parent / "minor_gc.py"
    cmd = [
        sys.executable,
        str(script),
        "--target",
        ".",
        "--max-files",
        str(cfg.get("max_files_per_run", 3)),
        "--max-seconds",
        str(cfg.get("max_seconds", 5)),
    ]
    if cfg.get("apply_safe"):
        cmd.append("--apply-safe")
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=max(1, int(cfg.get("max_seconds", 5)) + 1),
        check=False,
    )
    state = _load_state()
    state["last_minor_gc_rc"] = proc.returncode
    state["last_minor_gc_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if proc.returncode == 0:
        state["dirty_count_since_minor_gc"] = 0
        state["turns_since_minor_gc"] = 0
    _save_state(state)
    if proc.returncode == 0:
        print("context-gc: minor GC wrote .context-gc/minor-gc-report.md", file=sys.stderr)
    else:
        print("context-gc: minor GC failed; check hook stderr", file=sys.stderr)
    return proc.returncode


def minor_gc() -> int:
    cfg = _load_minor_gc_config()
    if not cfg.get("enabled") or not DIRTY.exists():
        return 0
    state = _load_state()
    dirty_count = int(state.get("dirty_count_since_minor_gc", state.get("dirty_count_since_mark", 0)))
    turns = int(state.get("turns_since_minor_gc", 0))
    if dirty_count >= int(cfg.get("interval_dirty_cards", 10)) or turns >= int(cfg.get("interval_turns", 10)):
        return _run_minor_gc(cfg)
    return 0


    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0



def _deny_pretool(reason: str) -> int:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def sweep_guard() -> int:
    raw, event = _read_raw_event()
    if not event:
        return 0
    tool = event.get("tool_name") or event.get("tool") or event.get("name") or ""
    if tool not in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        return 0
    paths = sorted(set(_walk_paths(event)))
    hits = [p for p in paths if _is_context_path(p)]
    if not hits:
        return 0
    if APPROVAL_MARKER in raw:
        return 0

    # Single-file edits still need room for normal work. MultiEdit is treated as broad because it
    # often rewrites sections inside a context root without listing every affected fact.
    broad = tool in {"MultiEdit", "NotebookEdit"} or len(hits) > 1
    high_risk = any(pathlib.PurePath(p.replace("\\", "/")).name in {"CLAUDE.md", "SOUL.md", "SKILL.md"} for p in hits)
    if not broad and not high_risk:
        return 0

    sample = ", ".join(hits[:5])
    more = f", and {len(hits) - 5} more" if len(hits) > 5 else ""
    reason = (
        "context-gc sweep guard blocked an unapproved context-bearing write. "
        f"Paths: {sample}{more}. Present a MARK report and sweep plan first, then retry with "
        f"'{APPROVAL_MARKER}' in the tool input after explicit user approval."
    )
    return _deny_pretool(reason)


def _review_nudge() -> None:
    """One terse line if drift decisions are waiting — never a dump."""
    if not REVIEW_QUEUE.exists():
        return
    try:
        data = json.loads(REVIEW_QUEUE.read_text(encoding="utf-8"))
    except Exception:
        return
    open_count = int(data.get("open", 0))
    if open_count <= 0:
        return
    print(
        f"context-gc: {open_count} drift decision(s) waiting — say `/context-gc review` to resolve.",
        file=sys.stderr,
    )


def stop_reminder() -> int:
    state = _load_state()
    state["turns_since_minor_gc"] = int(state.get("turns_since_minor_gc", 0)) + 1
    _save_state(state)
    minor_gc()
    _review_nudge()
    if not DIRTY.exists():
        return 0
    lines = [ln for ln in DIRTY.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return 0
    paths = []
    for line in lines:
        try:
            paths.append(json.loads(line).get("path"))
        except Exception:
            pass
    unique = sorted({p for p in paths if p})
    print(
        f"context-gc: {len(unique)} context-bearing file(s) changed. "
        "Run MARK on .context-gc/dirty.jsonl, then update SOURCES.md if needed.",
        file=sys.stderr,
    )
    for p in unique[:12]:
        print(f"  - {p}", file=sys.stderr)
    if LAST_AUTO_MARK.exists():
        print("  auto-MARK: see .context-gc/last-auto-mark.md", file=sys.stderr)
    if (STATE_DIR / "minor-gc-report.md").exists():
        print("  minor-GC: see .context-gc/minor-gc-report.md", file=sys.stderr)
    return 0


def clear() -> int:
    if DIRTY.exists():
        DIRTY.unlink()
        print("context-gc: cleared dirty cards")
    if STATE.exists():
        state = _load_state()
        state["dirty_count_since_mark"] = 0
        state["dirty_count_since_minor_gc"] = 0
        state["turns_since_minor_gc"] = 0
        _save_state(state)
    return 0


def self_test() -> int:
    samples = [
        {"tool_name": "Write", "tool_input": {"file_path": "docs/test.md"}},
        {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}},
        {"tool_name": "MultiEdit", "tool_input": {"file_path": "SKILL.md", "edits": []}},
    ]
    expected_paths = [["docs/test.md"], [], ["SKILL.md"]]
    for sample, expected in zip(samples, expected_paths):
        hits = [p for p in _walk_paths(sample) if _is_context_path(p)]
        if hits != expected:
            print(f"self-test failed: expected {expected}, got {hits}", file=sys.stderr)
            return 1
    deny = {
        "tool_name": "MultiEdit",
        "tool_input": {"file_path": "README.md", "edits": [{"old_string": "a", "new_string": "b"}]},
    }
    raw = json.dumps(deny)
    if APPROVAL_MARKER in raw:
        print("self-test failed: approval marker unexpectedly present", file=sys.stderr)
        return 1
    cfg = _load_auto_mark_config()
    if cfg["enabled"] is not False or cfg["threshold"] != 10 or cfg["max_seconds"] != 5:
        print("self-test failed: default auto_mark config should be disabled", file=sys.stderr)
        return 1
    mgc = _load_minor_gc_config()
    if mgc["enabled"] is not False or mgc["interval_dirty_cards"] != 10 or mgc["apply_safe"] is not False:
        print("self-test failed: default minor_gc config should be disabled", file=sys.stderr)
        return 1
    print("OK: context-gc hook helper self-test passed")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "--self-test":
        return self_test()
    if cmd == "dirty-card":
        return dirty_card()
    if cmd == "sweep-guard":
        return sweep_guard()
    if cmd == "stop-reminder":
        return stop_reminder()
    if cmd == "minor-gc":
        return minor_gc()
    if cmd == "clear":
        return clear()
    print("usage: context_gc_hook.py {dirty-card|sweep-guard|stop-reminder|minor-gc|clear|--self-test}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
