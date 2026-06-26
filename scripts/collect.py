#!/usr/bin/env python3
"""context-gc collect — the Sweep that can't lose data.

A garbage collector earns its name in the Sweep, not the Mark. But context-gc's "garbage" is a truth
judgment that can be wrong, so a real free() is unsafe — delete the wrong doc and it's gone. The
resolution: don't delete, MOVE to a recycle bin. Collected garbage leaves the live context (a real
sweep — the file is gone from where it rotted) yet stays fully recoverable (move, not delete). That is
the safe form of Sweep, and the only one compatible with context-gc's "never delete an original" rule.

  python scripts/collect.py --target . --collect <path> [--reason "..."] [--force]
  python scripts/collect.py --target . --restore <id>
  python scripts/collect.py --target . --list

Layout:
  .context-gc/collected/
    manifest.jsonl        append-only event log (collect / restore)
    <id>/<basename>       the collected item, byte-for-byte

Safety:
  - MOVE, never delete. Every collect is reversible with `restore`.
  - Protected roots (CLAUDE.md / SOUL.md / AGENTS.md / SOURCES.md / memory/** / skills/**) are refused
    unless --force — context-gc must not quietly sweep an agent's own root context.
  - Every collect and restore appends to decisions.jsonl with reversible=true.
This script moves files only between the target and its own .context-gc/collected/. It never deletes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import current_scope  # noqa: E402

MANIFEST = "manifest.jsonl"
DECISIONS = "decisions.jsonl"


def _state(target: pathlib.Path) -> pathlib.Path:
    s = target / ".context-gc"
    s.mkdir(exist_ok=True)
    return s


def _bin(target: pathlib.Path) -> pathlib.Path:
    b = _state(target) / "collected"
    b.mkdir(exist_ok=True)
    return b


def _is_protected(rel: str) -> bool:
    """An agent's own root context must never be swept without an explicit --force."""
    low = rel.replace("\\", "/").lower()
    name = low.rsplit("/", 1)[-1]
    if name in {"claude.md", "soul.md", "agents.md", "sources.md"}:
        return True
    for seg in ("memory/", "skills/", "/adr/", "/sdd"):
        if low.startswith(seg.lstrip("/")) or seg in f"/{low}":
            return True
    return False


def _events(target: pathlib.Path) -> list[dict]:
    mf = _bin(target) / MANIFEST
    if not mf.exists():
        return []
    out = []
    for line in mf.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _append(target: pathlib.Path, name: str, record: dict) -> None:
    with (_bin(target) / name if name == MANIFEST else _state(target) / name).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _live(target: pathlib.Path) -> dict[str, dict]:
    """Current recycle-bin state: id -> collect record, for ids whose latest event is a collect."""
    state: dict[str, dict] = {}
    for ev in _events(target):
        cid = ev.get("id")
        if not cid:
            continue
        if ev.get("event") == "collect":
            state[cid] = ev
        elif ev.get("event") == "restore":
            state.pop(cid, None)
    return state


def cmd_collect(target: pathlib.Path, rel_path: str, reason: str, force: bool) -> int:
    src = (target / rel_path).resolve()
    try:
        rel = src.relative_to(target).as_posix()
    except ValueError:
        print(json.dumps({"error": f"path is outside target: {rel_path}"}))
        return 1
    if not src.exists():
        print(json.dumps({"error": f"nothing to collect, path does not exist: {rel}"}))
        return 1
    if _is_protected(rel) and not force:
        print(json.dumps({"error": f"refused: `{rel}` is a protected agent root; pass --force to override", "protected": True}))
        return 2
    cid = time.strftime("%Y%m%dT%H%M%S") + "-" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:6]
    dest_dir = _bin(target) / cid
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.move(str(src), str(dest))
    rec = {
        "event": "collect", "id": cid, "original_path": rel, "basename": src.name,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"), "scope": current_scope(target),
        "reason": reason or "", "protected_override": bool(_is_protected(rel) and force),
    }
    _append(target, MANIFEST, rec)
    _append(target, DECISIONS, {
        "ts": rec["at"], "item": f"collect:{cid}", "kind": "collect",
        "action": {"op": "collect", "path": rel}, "by": "agent", "reversible": True,
        "originals_kept": [f".context-gc/collected/{cid}/{src.name}"], "scope": rec["scope"], "reason": reason or "",
    })
    print(json.dumps({"collected": rel, "id": cid, "restore_with": f"collect.py --restore {cid}", "reversible": True}, ensure_ascii=False))
    return 0


def cmd_restore(target: pathlib.Path, cid: str) -> int:
    rec = _live(target).get(cid)
    if not rec:
        print(json.dumps({"error": f"no collected item with id {cid} (already restored, or never collected)"}))
        return 1
    dest = (target / rec["original_path"])
    if dest.exists():
        print(json.dumps({"error": f"cannot restore: `{rec['original_path']}` already exists again; move it aside first"}))
        return 2
    stored = _bin(target) / cid / rec["basename"]
    if not stored.exists():
        print(json.dumps({"error": f"recycle-bin copy missing for {cid}; manifest and storage disagree"}))
        return 3
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(stored), str(dest))
    try:
        (_bin(target) / cid).rmdir()
    except OSError:
        pass
    at = time.strftime("%Y-%m-%d %H:%M:%S")
    _append(target, MANIFEST, {"event": "restore", "id": cid, "original_path": rec["original_path"], "at": at})
    _append(target, DECISIONS, {
        "ts": at, "item": f"restore:{cid}", "kind": "restore",
        "action": {"op": "restore", "path": rec["original_path"]}, "by": "agent", "reversible": True, "scope": current_scope(target),
    })
    print(json.dumps({"restored": rec["original_path"], "id": cid}, ensure_ascii=False))
    return 0


def cmd_list(target: pathlib.Path) -> int:
    live = _live(target)
    if not live:
        print("context-gc recycle bin is empty — nothing collected.")
        return 0
    print(f"context-gc recycle bin — {len(live)} item(s) collected (all restorable):")
    for cid, rec in sorted(live.items()):
        print(f"  [{cid}] {rec['original_path']}  — {rec.get('reason') or 'no reason given'}  (collected {rec['at']})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="context-gc recycle bin: sweep garbage by moving it, never deleting")
    ap.add_argument("--target", default=".")
    ap.add_argument("--collect", metavar="PATH", help="move this path into the recycle bin")
    ap.add_argument("--restore", metavar="ID", help="restore a collected item by id")
    ap.add_argument("--list", action="store_true", help="list what is currently in the recycle bin")
    ap.add_argument("--reason", default="", help="why this is garbage (recorded in the manifest)")
    ap.add_argument("--force", action="store_true", help="allow collecting a protected agent root")
    a = ap.parse_args()
    target = pathlib.Path(a.target).resolve()
    if not target.is_dir():
        print(json.dumps({"error": f"target is not a directory: {target}"}))
        return 1
    if a.collect:
        return cmd_collect(target, a.collect, a.reason, a.force)
    if a.restore:
        return cmd_restore(target, a.restore)
    if a.list:
        return cmd_list(target)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
