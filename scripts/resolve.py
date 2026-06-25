#!/usr/bin/env python3
"""Agent self-resolve path — close the review queue without a human, within policy.

context-gc is agent-first: a loop/agent drives it and resolves the drift it is *allowed* to. This is
the non-interactive counterpart to the SKILL `review` flow (which asks a human). It reads the review
queue + the autonomy policy, resolves only what policy permits, escalates the rest, and writes an
audit trail. The human owns the boundary (config) and audits the log; the agent acts within it.

Hard guarantees (the principal-agent safety net):
  - The NEVER_AUTO floor in _common.py is enforced regardless of config level — even level=full will
    not auto-resolve protected / delete / memory-condense / unknown-root items.
  - Originals are never deleted by an agent resolve; superseded files are archived, not removed.
  - Every agent resolution appends to .context-gc/decisions.jsonl with evidence + reversibility.

Usage:
  python scripts/resolve.py --target . --auto                 # resolve all policy-allowed items
  python scripts/resolve.py --target . --item <id> --choice N # explicit single resolution
  python scripts/resolve.py --target . --log                  # print the audit trail
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import agent_may_resolve, current_scope, load_autonomy_policy  # noqa: E402
import minor_gc  # noqa: E402

QUEUE = "review-queue.json"
DECISIONS = "decisions.jsonl"
PATTERNS = "patterns.jsonl"


def _state(target: pathlib.Path) -> pathlib.Path:
    d = target / ".context-gc"
    d.mkdir(exist_ok=True)
    return d


def _load_queue(target: pathlib.Path) -> dict[str, Any]:
    path = _state(target) / QUEUE
    if not path.exists():
        return {"open": 0, "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"open": 0, "items": []}


def _save_queue(target: pathlib.Path, queue: dict[str, Any]) -> None:
    queue["open"] = sum(1 for it in queue.get("items", []) if it.get("status") == "open")
    (_state(target) / QUEUE).write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


def _domain_for_item(target: pathlib.Path, item: dict[str, Any]) -> minor_gc.Domain | None:
    """Find the SOURCES.md domain whose root/copies overlap the item's evidence."""
    evidence = {e.split(":", 1)[0].replace("\\", "/") for e in item.get("evidence", [])}
    for domain in minor_gc.parse_sources(target / "SOURCES.md"):
        paths = {domain.root, *domain.copies}
        if evidence & {p for p in paths if p}:
            return domain
    return None


def _append_audit(target: pathlib.Path, record: dict[str, Any]) -> None:
    with (_state(target) / DECISIONS).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _record_pattern(target: pathlib.Path, record: dict[str, Any]) -> None:
    """Sediment a successful agent resolution into patterns.jsonl for the hill-climb loop.

    analyze_patterns.py clusters these to find drift that recurs; the evol loop turns recurring
    clusters into proposals. Every pattern carries its scope (git branch/sha) so feature-branch
    learnings never pollute main's optimization — the cross-scope guard from next-phase-design.md.
    Only applied resolutions become patterns; escalations and no-ops do not.
    """
    if not record.get("applied"):
        return
    action = record.get("action", {})
    evidence = record.get("evidence", [])
    pattern = {
        "id": f"{record.get('kind', 'drift')}-{record.get('item', '')[:12]}",
        "kind": record.get("kind", "drift"),
        "source": record.get("by", "agent") + "_resolve",
        "ts": record.get("ts"),
        "scope": record.get("scope"),
        "signature": {
            "op": str(action.get("op", "")),
            "evidence": evidence,
            "root_file": evidence[0].split(":", 1)[0] if evidence else "",
            "copy_file": evidence[1].split(":", 1)[0] if len(evidence) > 1 else "",
        },
    }
    with (_state(target) / PATTERNS).open("a", encoding="utf-8") as f:
        f.write(json.dumps(pattern, ensure_ascii=False) + "\n")


def _execute(target: pathlib.Path, item: dict[str, Any], choice: int, cfg: dict[str, Any], by: str, level: str) -> dict[str, Any]:
    """Execute the chosen option's declarative action. Returns an audit record."""
    options = item.get("options", [])
    action = options[choice].get("action", {}) if 0 <= choice < len(options) else {}
    op = str(action.get("op", "")).lower()
    domain = _domain_for_item(target, item)
    protected = cfg.get("protected", minor_gc.DEFAULT_PROTECTED)
    originals_kept: list[str] = []
    applied = False
    detail = ""

    if op in {"scalar_sync", "reconcile_to_root"} and domain is not None:
        results = minor_gc.scalar_sync(target, domain, apply=True, protected=protected)
        applied = any(r["status"] == "AUTO_FIXED" for r in results)
        detail = "; ".join(r["detail"] for r in results)
    elif op == "pointer_copy" and domain is not None:
        results = minor_gc.pointer_copy(target, domain, apply=True, protected=protected)
        applied = any(r["status"] == "AUTO_FIXED" for r in results)
        detail = "; ".join(r["detail"] for r in results)
    elif op == "mark_fork" and domain is not None:
        applied = _set_sources_status(target, domain.name, "FORK")
        detail = f"marked `{domain.name}` FORK (intentional divergence)"
    elif op == "mark_historical" and domain is not None:
        applied = _set_sources_status(target, domain.name, "HISTORICAL")
        detail = f"marked `{domain.name}` HISTORICAL (preserved as history)"
    else:
        # Anything else (set_current_memory, consolidate_anchor, flag_implementation_gap, manual,
        # defer, or no matching domain) is human-reserved and must not be auto-executed here.
        detail = f"op `{op}` is human-reserved or no SOURCES domain matched; not auto-executed"

    return {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "item": item.get("id"),
        "kind": item.get("kind"),
        "choice": choice,
        "action": action,
        "by": by,
        "evidence": item.get("evidence", []),
        "policy_level": level,
        "applied": applied,
        "detail": detail,
        "reversible": True,  # all current ops are git-reversible; no original is deleted
        "originals_kept": originals_kept,
        "scope": current_scope(target),  # which git branch/sha this decision belongs to (cross-scope guard)
    }


def _set_sources_status(target: pathlib.Path, domain_name: str, status: str) -> bool:
    """Set a domain's Status line in SOURCES.md. Returns True if changed."""
    src = target / "SOURCES.md"
    if not src.exists():
        return False
    lines = src.read_text(encoding="utf-8").splitlines()
    in_domain = False
    changed = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("###"):
            in_domain = domain_name in line
        elif in_domain and line.strip().startswith("- **Status:**"):
            lines[i] = f"- **Status:** `{status}`"
            changed = True
            in_domain = False
    if changed:
        src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def cmd_auto(target: pathlib.Path) -> int:
    cfg = minor_gc.load_config(target)
    policy = load_autonomy_policy(target)
    level = policy.get("level", "assist")
    queue = _load_queue(target)
    resolved = escalated = 0
    for item in queue.get("items", []):
        if item.get("status") != "open":
            continue
        if not agent_may_resolve(item, policy):
            escalated += 1
            continue
        record = _execute(target, item, item.get("recommend", 0), cfg, by="agent", level=level)
        _append_audit(target, record)
        _record_pattern(target, record)
        if record["applied"]:
            item["status"] = "resolved"
            resolved += 1
        else:
            escalated += 1
    _save_queue(target, queue)
    summary = {"resolved": resolved, "escalated": escalated, "audit": f".context-gc/{DECISIONS}", "level": level}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def cmd_item(target: pathlib.Path, item_id: str, choice: int) -> int:
    cfg = minor_gc.load_config(target)
    policy = load_autonomy_policy(target)
    queue = _load_queue(target)
    item = next((it for it in queue.get("items", []) if it.get("id") == item_id), None)
    if item is None:
        print(json.dumps({"error": f"item {item_id} not found"}))
        return 1
    # Explicit single resolve still honors the never_auto floor for agent callers; a human-driven
    # SKILL review may pass any choice, but this CLI path is agent-facing and stays gated.
    if not agent_may_resolve({**item, "recommend": choice}, policy):
        print(json.dumps({"error": "policy/floor forbids auto-resolving this item; escalate to a human"}))
        return 2
    record = _execute(target, item, choice, cfg, by="agent", level=policy.get("level", "assist"))
    _append_audit(target, record)
    _record_pattern(target, record)
    if record["applied"]:
        item["status"] = "resolved"
    _save_queue(target, queue)
    print(json.dumps(record, ensure_ascii=False))
    return 0


def cmd_log(target: pathlib.Path) -> int:
    path = _state(target) / DECISIONS
    if not path.exists():
        print("context-gc: no decision log yet.")
        return 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        mark = "✓" if r.get("applied") else "·"
        print(f"{mark} {r.get('ts')}  [{r.get('kind')}] {r.get('detail', '')}  (by {r.get('by')}, {r.get('policy_level')})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent self-resolve the review queue within autonomy policy")
    ap.add_argument("--target", default=".")
    ap.add_argument("--auto", action="store_true", help="resolve all policy-allowed open items")
    ap.add_argument("--item", help="resolve a single item by id")
    ap.add_argument("--choice", type=int, help="option index for --item")
    ap.add_argument("--log", action="store_true", help="print the decision audit trail")
    args = ap.parse_args()

    target = pathlib.Path(args.target).resolve()
    if not target.is_dir():
        print(f"FAIL: target is not a directory: {target}")
        return 1
    if args.log:
        return cmd_log(target)
    if args.item is not None:
        if args.choice is None:
            print("FAIL: --item requires --choice")
            return 1
        return cmd_item(target, args.item, args.choice)
    if args.auto:
        return cmd_auto(target)
    print("usage: resolve.py --target . {--auto | --item <id> --choice N | --log}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
