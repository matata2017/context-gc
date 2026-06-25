#!/usr/bin/env python3
"""Aggregate open drift decisions into one review queue for the SKILL to act on.

context-gc's scripts detect drift but never decide truth. When a finding needs a human
("which value is current?", "is this a fork?"), this aggregator collects it from the existing
detection outputs into ONE machine-readable queue:

  .context-gc/review-queue.json

The SKILL `review` workflow reads that queue and asks the user one AskUserQuestion per item, then
performs the chosen declarative `action`. This script is deterministic and non-interactive: it only
proposes labeled options + a recommendation; it never edits project files and never picks an answer.

Sources aggregated:
  - .context-gc/findings.json   (mark.py)        — UNKNOWN_ROOT / high-severity drift candidates
  - .context-gc/minor-gc.json   (minor_gc.py)    — NEEDS_REVIEW / *_SKIP results
  - .context-gc/memory-gc.json  (minor_gc.py)    — CONFLICT_NEEDS_REVIEW memory entries
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import time
from typing import Any

# Finding types/statuses that genuinely need a human decision (not just informational bloat notes).
REVIEW_STATUSES = {"UNKNOWN_ROOT", "DRIFTED"}
REVIEW_KINDS = {
    "memory-conflict",
    "profile-drift",
    "semantic-instruction-cluster",
    "tone-behavior-drift",
    "spec-drift",
    "sdd-drift",
    "contradiction",
}


def _id(kind: str, evidence: list[str]) -> str:
    raw = kind + "|" + "|".join(sorted(evidence))
    return kind + "-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def _evidence(item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if item.get("file"):
        loc = f":{item['line']}" if item.get("line") else ""
        out.append(f"{item['file']}{loc}")
    for f in item.get("files", []):
        out.append(f)
    return out


def _options_for(kind: str, evidence: list[str]) -> tuple[list[dict[str, Any]], int]:
    """Propose labeled, declarative options. recommend index, or -1 when truly ambiguous."""
    first = evidence[0] if evidence else "source A"
    last = evidence[-1] if len(evidence) > 1 else "source B"
    if kind in {"memory-conflict", "profile-drift"}:
        return (
            [
                {"label": f"Keep {first} as current", "action": {"op": "set_current_memory", "from": first}},
                {"label": f"Keep {last} as current", "action": {"op": "set_current_memory", "from": last}},
                {"label": "Both — scope by context (FORK)", "action": {"op": "mark_fork", "paths": evidence}},
            ],
            -1,
        )
    if kind in {"semantic-instruction-cluster", "tone-behavior-drift"}:
        return (
            [
                {"label": f"Anchor policy on {first}", "action": {"op": "consolidate_anchor", "root": first, "copies": evidence}},
                {"label": f"Anchor policy on {last}", "action": {"op": "consolidate_anchor", "root": last, "copies": evidence}},
                {"label": "Keep both as scoped FORK", "action": {"op": "mark_fork", "paths": evidence}},
            ],
            -1,
        )
    if kind in {"spec-drift", "sdd-drift", "contradiction"}:
        return (
            [
                {"label": "Update doc to match code/tests", "action": {"op": "reconcile_to_root", "root": "code"}},
                {"label": "Code is incomplete — keep spec, flag gap", "action": {"op": "flag_implementation_gap"}},
                {"label": "Doc is historical — preserve", "action": {"op": "mark_historical", "paths": evidence}},
            ],
            -1,
        )
    # Generic decision: resolve manually or defer.
    return (
        [
            {"label": "Resolve now (I will edit)", "action": {"op": "manual"}},
            {"label": "Defer this decision", "action": {"op": "defer"}},
        ],
        0,
    )


def _load(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# Kinds whose resolution touches sensitive agent context — the agent must escalate these to a human.
_SENSITIVE_KINDS = {"memory-conflict", "profile-drift", "midterm-expired", "semantic-instruction-cluster", "tone-behavior-drift"}
_SAFE_MECHANICAL_KINDS = {"scalar-sync", "pointer-copy", "generated-state-cleanup", "minor-gc-review"}


def _policy_class(kind: str, evidence: list[str]) -> str:
    """Tag an item so the autonomy resolver knows whether an agent may touch it.

    - `protected` if any evidence path is an agent root / memory / skill / adr / sdd.
    - `sensitive` for memory/profile/instruction/tone drift (human-reserved by default).
    - `safe-mechanical` for ports/pointers/generated state.
    - `review` otherwise (escalates unless the user widens the policy).
    """
    for path in evidence:
        p = path.replace("\\", "/").lower()
        name = p.rsplit("/", 1)[-1]
        if name in {"claude.md", "soul.md"} or "/memory/" in f"/{p}" or "/skills/" in f"/{p}" or "/adr/" in f"/{p}" or "/sdd" in p:
            return "protected"
    if kind in _SENSITIVE_KINDS:
        return "sensitive"
    if kind in _SAFE_MECHANICAL_KINDS:
        return "safe-mechanical"
    return "review"


def build_queue(state: pathlib.Path) -> list[dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}

    def add(kind: str, summary: str, evidence: list[str], detail: str) -> None:
        if not evidence:
            evidence = [summary[:40]]
        item_id = _id(kind, evidence)
        if item_id in items:
            return
        options, recommend = _options_for(kind, evidence)
        items[item_id] = {
            "id": item_id,
            "kind": kind,
            "summary": summary,
            "detail": detail,
            "evidence": evidence,
            "options": options,
            "recommend": recommend,
            "policy_class": _policy_class(kind, evidence),
            "status": "open",
        }

    findings = _load(state / "findings.json").get("findings", [])
    for f in findings:
        kind = str(f.get("type", "")).lower()
        status = str(f.get("status", "")).upper()
        if kind in REVIEW_KINDS or status in REVIEW_STATUSES and f.get("severity") in {"high", "medium"}:
            add(kind or "drift", f.get("detail", kind), _evidence(f), f.get("needs_judgment", ""))

    for r in _load(state / "minor-gc.json").get("results", []):
        if r.get("status") in {"NEEDS_REVIEW", "CONFLICT_NEEDS_REVIEW", "UNKNOWN_ROOT_SKIP"}:
            ev = [r["path"]] if r.get("path") else []
            kind = "memory-conflict" if r.get("status") == "CONFLICT_NEEDS_REVIEW" else "minor-gc-review"
            add(kind, f"{r.get('domain', 'domain')}: {r.get('detail', '')}", ev, r.get("detail", ""))

    for e in _load(state / "memory-gc.json").get("entries", []):
        if e.get("status") == "CONFLICT_NEEDS_REVIEW":
            add("memory-conflict", f"{e.get('domain', 'memory')}: {e.get('detail', '')}", e.get("sources", []), e.get("detail", ""))

    return list(items.values())


def main() -> int:
    ap = argparse.ArgumentParser(description="Aggregate open drift decisions into a review queue")
    ap.add_argument("--target", default=".")
    ap.add_argument("--json-only", action="store_true", help="print only the queue path")
    args = ap.parse_args()

    target = pathlib.Path(args.target).resolve()
    if not target.is_dir():
        print(f"FAIL: target is not a directory: {target}")
        return 1
    state = target / ".context-gc"
    state.mkdir(exist_ok=True)
    queue = build_queue(state)
    out = state / "review-queue.json"
    out.write_text(
        json.dumps(
            {"target": target.name, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "open": len(queue), "items": queue},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if args.json_only:
        print(out)
        return 0
    if not queue:
        print("context-gc: review queue is empty — no decisions waiting.")
        return 0
    print(f"context-gc: {len(queue)} drift decision(s) waiting in {out.relative_to(target)}")
    for it in queue:
        print(f"  - [{it['kind']}] {it['summary'][:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
