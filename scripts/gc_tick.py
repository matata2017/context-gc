#!/usr/bin/env python3
"""gc_tick — one idempotent governance tick any loop engine or agent can call.

This is context-gc's entry point for autonomous use. A single tick chains the existing deterministic
runners and returns ONE structured result object:

  mark.py --dirty-only    →  detect drift candidates (read-only)
  minor_gc.py             →  apply pre-authorized contract fixes (config-gated)
  review_queue.py         →  aggregate open decisions into the queue
  resolve.py --auto       →  agent self-resolves what autonomy policy allows; escalates the rest
  analyze_patterns.py     →  Layer 4 hill climbing — suggest optimizations from accumulated patterns

It never blocks on a human. Pending decisions accumulate in the queue for the next human touch or for
a loop's --emit-tasks adapter.

Design note: every tick produces a TickResult (the `result` dict below). Phase-3 loop adapters
(--gate as a verify_cmd, --loop-state to compact the loop's own memory, --emit-tasks to spawn
orchestrator tasks) are thin wrappers over this object — they read it, they don't re-run the chain.

Usage:
  python scripts/gc_tick.py --target .            # full tick, print TickResult json
  python scripts/gc_tick.py --target . --quiet    # run, print only the one-line summary
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import is_git_repo, scope_changed, write_scope  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent


def _run(script: str, *args: str, target: pathlib.Path, timeout: int = 60) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [sys.executable, str(HERE / script), "--target", str(target), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout
    except Exception as exc:  # subprocess failure must not crash the tick
        return 1, f'{{"error": "{type(exc).__name__}: {exc}"}}'


def _load_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_tick(target: pathlib.Path) -> dict:
    """Run one governance tick and return a structured TickResult."""
    state = target / ".context-gc"
    state.mkdir(exist_ok=True)
    steps: dict[str, int] = {}

    # 0) scope check — if the git branch moved since we last ran, the working-tree ground truth
    # changed wholesale; old dirty cards point at files that may now be entirely different. Invalidate
    # them BEFORE mark reads them, and record the new scope. (A new commit on the same branch is normal
    # incremental work and is not treated as a scope change.) Outside a git repo there is no branch, so
    # this whole step is skipped — non-git targets keep their dirty cards untouched.
    scope_note = None
    new_scope = None
    if is_git_repo(target):
        changed, old_scope, new_scope = scope_changed(target)
        if changed:
            dirty = state / "dirty.jsonl"
            if dirty.exists():
                dirty.unlink()
            scope_note = f"branch {old_scope['branch']} → {new_scope['branch']}: stale dirty cards invalidated"
        write_scope(target, new_scope)

    # 1) detect (read-only).  Use --dirty-only for cheap incremental ticks, but fall back
    #    to a full scan when there are no findings yet (first tick after init, or after a
    #    scope change wiped them).  A full scan on first tick ensures the agent sees drift
    #    immediately instead of ticking to zero until the first edit creates a dirty card.
    existing_findings = (state / "findings.json").exists() and bool(_load_json(state / "findings.json").get("findings"))
    mark_args = ["--dirty-only", "--json-only"] if existing_findings else ["--json-only"]
    steps["mark"], _ = _run("mark.py", *mark_args, target=target)
    cfg_path = target / ".context-gc" / "config.yml"
    cfg_minor_apply_safe = False
    if cfg_path.exists():
        try:
            for raw in cfg_path.read_text(encoding="utf-8").splitlines():
                stripped = raw.strip()
                if stripped.startswith("apply_safe:"):
                    cfg_minor_apply_safe = stripped.split(":", 1)[1].strip().lower() == "true"
        except Exception:
            cfg_minor_apply_safe = False

    # 2) apply pre-authorized contract fixes (minor_gc honors config apply_safe + protected).
    minor_args = ["--apply-safe"] if cfg_minor_apply_safe else []
    steps["minor_gc"], _ = _run("minor_gc.py", *minor_args, target=target)
    # 3) aggregate open decisions into the review queue.
    steps["review_queue"], _ = _run("review_queue.py", "--json-only", target=target)
    # 4) agent self-resolve within autonomy policy.
    rc, resolve_out = _run("resolve.py", "--auto", target=target)
    steps["resolve"] = rc
    resolve_summary = {}
    try:
        resolve_summary = json.loads(resolve_out.strip().splitlines()[-1]) if resolve_out.strip() else {}
    except Exception:
        resolve_summary = {}
    # 5) hill climbing — analyze accumulated patterns, generate optimization proposals (read-only).
    steps["analyze"], _ = _run("analyze_patterns.py", "--json-only", target=target)

    minor = _load_json(state / "minor-gc.json")
    auto_fixed = sum(1 for r in minor.get("results", []) if r.get("status") in {"AUTO_FIXED", "CURRENT_MEMORY_WRITTEN"})
    queue = _load_json(state / "review-queue.json")
    pending = sum(1 for it in queue.get("items", []) if it.get("status") == "open")
    proposals = _load_json(state / "optimization-proposals.json")
    proposal_count = proposals.get("proposal_count", 0)

    result = {
        "tick_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "target": target.name,
        "auto_fixed": auto_fixed,                                # minor_gc contract fixes
        "agent_resolved": int(resolve_summary.get("resolved", 0)),  # resolve.py within policy
        "escalated": int(resolve_summary.get("escalated", 0)),      # left for a human / loop tasks
        "pending": pending,                                      # open queue items
        "optimization_proposals": proposal_count,               # Layer 4 hill-climb suggestions
        "policy_level": resolve_summary.get("level", "assist"),
        "scope": new_scope,                                      # git branch + HEAD this tick ran under
        "scope_note": scope_note,                                # set when a branch switch invalidated stale state
        "steps_rc": steps,
        "audit": ".context-gc/decisions.jsonl",
        "queue": ".context-gc/review-queue.json",
    }
    (state / "tick.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="One governance tick for loop engines / agents")
    ap.add_argument("--target", default=".")
    ap.add_argument("--quiet", action="store_true", help="print only the one-line summary")
    args = ap.parse_args()

    target = pathlib.Path(args.target).resolve()
    if not target.is_dir():
        print(f"FAIL: target is not a directory: {target}")
        return 1
    result = run_tick(target)
    if args.quiet:
        print(
            f"context-gc tick: auto_fixed={result['auto_fixed']} agent_resolved={result['agent_resolved']} "
            f"escalated={result['escalated']} pending={result['pending']} (level={result['policy_level']})"
        )
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
