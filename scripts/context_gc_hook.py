#!/usr/bin/env python3
"""context-gc hook helper.

Subcommands:
  dirty-card     Read Claude Code hook JSON from stdin; if a context-bearing path changed,
                 append a dirty card to .context-gc/dirty.jsonl.
  stop-reminder  Print a short reminder if dirty cards exist.
  clear          Clear dirty cards after a successful MARK/SWEEP/BARRIER run.

The script is intentionally conservative: it never edits project files except its own
.context-gc/dirty.jsonl state file.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import Any, Iterable

STATE_DIR = pathlib.Path(".context-gc")
DIRTY = STATE_DIR / "dirty.jsonl"

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


def _read_event() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


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
    print(f"context-gc: marked {len(hits)} dirty context file(s)", file=sys.stderr)
    return 0


def stop_reminder() -> int:
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
    if len(unique) > 12:
        print(f"  ... and {len(unique) - 12} more", file=sys.stderr)
    return 0


def clear() -> int:
    if DIRTY.exists():
        DIRTY.unlink()
        print("context-gc: cleared dirty cards")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "dirty-card":
        return dirty_card()
    if cmd == "stop-reminder":
        return stop_reminder()
    if cmd == "clear":
        return clear()
    print("usage: context_gc_hook.py {dirty-card|stop-reminder|clear}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
