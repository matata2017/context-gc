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
        if name in {"claude.md", "soul.md", "agents.md", "sources.md"} or "/memory/" in f"/{p}" or "/skills/" in f"/{p}" or "/adr/" in f"/{p}" or "/sdd" in p:
            return "protected"
    if kind in _SENSITIVE_KINDS:
        return "sensitive"
    if kind in _SAFE_MECHANICAL_KINDS:
        return "safe-mechanical"
    return "review"


def _why(kind: str, policy_class: str, recommend: int, evidence: list[str]) -> str:
    """One human-facing line: why this decision is in front of YOU and was not auto-resolved.

    Good human-in-the-loop UX starts with 'why am I being asked'. Without it an escalated item looks
    like an unattended chore an eager agent will 'just finish' — the exact failure a driving agent hit.
    """
    n = len(evidence)
    if policy_class == "protected":
        return ("Touches a protected root (agent instructions / memory / SDD). context-gc never "
                "auto-edits these — the decision is yours, so it waited for you.")
    if policy_class == "sensitive":
        return ("Agent memory/instruction drift — auto-merging could poison future context, so it is "
                "reserved for your call.")
    if recommend == -1:
        return (f"The {n} sources genuinely conflict and none is provably the root. context-gc won't "
                "guess truth: pick the current one, or scope them as an intentional FORK.")
    return "A quick call — resolve now or defer. Low risk, but context-gc leaves truth to you."


def _snippet(target: pathlib.Path, ev: str) -> str:
    """A short content preview for an evidence path so the reviewer need not open the file."""
    path, _, line = ev.partition(":")
    try:
        lines = (target / path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return ev
    if line.isdigit() and 1 <= int(line) <= len(lines):
        text = lines[int(line) - 1].strip()
    else:
        text = next((ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")), "")
    return f'{ev}  "{text[:80]}"' if text else ev


def build_queue(target: pathlib.Path) -> list[dict[str, Any]]:
    state = target / ".context-gc"
    items: dict[str, dict[str, Any]] = {}

    def add(kind: str, summary: str, evidence: list[str], detail: str) -> None:
        if not evidence:
            evidence = [summary[:40]]
        item_id = _id(kind, evidence)
        if item_id in items:
            return
        options, recommend = _options_for(kind, evidence)
        policy_class = _policy_class(kind, evidence)
        items[item_id] = {
            "id": item_id,
            "kind": kind,
            "summary": summary,
            "detail": detail,
            "evidence": evidence,
            "evidence_preview": [_snippet(target, e) for e in evidence],
            "why": _why(kind, policy_class, recommend, evidence),
            "options": options,
            "recommend": recommend,
            "policy_class": policy_class,
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

    # Mark → Sweep bridge: when several dead references pile up in ONE file, the whole file may be a
    # refactor leftover — but whether it IS garbage is a judgment (a doc can have valid content plus a
    # few stale lines). So we don't auto-collect; we raise ONE decision per such file offering `collect`
    # (move to the recycle bin, reversible) vs fix-in-place, and leave the call to the human (recommend
    # -1). Protected agent roots (CLAUDE.md/AGENTS.md/SOURCES.md/memory/skills) never get a collect
    # option — they are roots, not leftovers; fix their lines instead.
    orphan_count: dict[str, int] = {}
    # Also collect the actual finding details per file for evidence_preview.
    orphan_details: dict[str, list[str]] = {}
    for f in findings:
        if f.get("type") in {"orphan-reference", "orphan-command-ref"}:
            for loc in _evidence(f):
                fp = loc.split(":", 1)[0]
                orphan_count[fp] = orphan_count.get(fp, 0) + 1
                detail = f.get("detail", "")
                if detail:
                    orphan_details.setdefault(fp, []).append(detail)
    for fp, count in sorted(orphan_count.items()):
        if count < 3:
            continue
        item_id = _id("stale-file-candidate", [fp])
        if item_id in items:
            continue
        protected = _policy_class("", [fp]) == "protected"
        options: list[dict[str, Any]] = []
        if not protected:
            options.append({"label": f"Collect `{fp}` to the recycle bin (reversible)",
                            "action": {"op": "collect", "path": fp, "reason": f"{count} dead references — suspected refactor leftover"}})
        options.append({"label": "Keep the file; fix the dead references in place", "action": {"op": "manual"}})
        why = (f"`{fp}` has {count} references pointing at things that no longer exist. The whole file may "
               "be a leftover from a refactor — or still useful with a few stale lines. You decide.")
        if protected:
            why += " It is a protected agent root, so fix the lines in place rather than collecting it."
        else:
            why += " Sweep it to the recycle bin (one-command undo), or fix the lines in place."
        # Build evidence_preview from the actual orphan findings for this file — not the
        # generic file-first-line that _snippet falls back to when there is no line number.
        details = orphan_details.get(fp, [])
        preview = details[:5] if details else [_snippet(target, fp)]
        items[item_id] = {
            "id": item_id, "kind": "stale-file-candidate",
            "summary": f"`{fp}` has {count} dead references — whole file a refactor leftover?",
            "detail": f"{count} references in {fp} point at files/scripts that no longer exist",
            "evidence": [fp], "evidence_preview": preview, "why": why,
            "options": options, "recommend": -1,
            "policy_class": "protected" if protected else "review", "status": "open",
        }

    # Deduplicate: when a stale-file-candidate already covers a file's dead references,
    # suppress the individual orphan items for that file — the user sees the aggregated
    # decision card instead of the same facts twice.
    stale_files = {fp for fp, c in orphan_count.items() if c >= 3}
    if stale_files:
        drop_ids: set[str] = set()
        for iid, it in items.items():
            if it["kind"] in {"orphan-reference", "orphan-command-ref"}:
                ev_files = {e.split(":", 1)[0] for e in it.get("evidence", [])}
                if ev_files & stale_files:
                    drop_ids.add(iid)
        for iid in drop_ids:
            del items[iid]

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
    queue = build_queue(target)
    scope = _load(state / "findings.json").get("scope")  # inherit the git scope of the findings we aggregated
    out = state / "review-queue.json"
    out.write_text(
        json.dumps(
            {"target": target.name, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "scope": scope, "open": len(queue), "items": queue},
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
