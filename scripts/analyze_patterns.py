#!/usr/bin/env python3
"""Layer 4 — 爬坡循环（Hill Climbing）分析引擎。

扫描 patterns.jsonl（agent 成功自决沉淀的漂移模式，每条带 scope 分支标注），发现重复出现的
模式并聚类，自动生成 SOURCES.md / 检测规则的优化方案。人审核后 apply。

跨 scope 重复（多个分支都出现同一模式）是更强的证据——见 research/next-phase-design.md。

这是 Loop Engineering 第四层的核心——让系统自己学会更好地检测漂移。

用法：
  python scripts/analyze_patterns.py --target .                    # 分析，打印建议
  python scripts/analyze_patterns.py --target . --min-occurrences 3 # 至少出现 3 次才建议
  python scripts/analyze_patterns.py --target . --apply proposal-1  # 应用指定建议
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import time
from collections import defaultdict


def _load_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _load_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cluster_key(pattern: dict) -> str:
    """生成聚类键——相同 kind + 相同 root-file 的模式归为一类。"""
    kind = pattern.get("kind", "")
    domain = pattern.get("domain", "")
    sig = pattern.get("signature", {})
    root = sig.get("root_file", sig.get("root", ""))
    copy = sig.get("copy_file", sig.get("copy", ""))
    return f"{kind}|{domain}|{root}|{copy}"


def _cluster(patterns: list[dict]) -> dict[str, list[dict]]:
    clusters: dict[str, list[dict]] = defaultdict(list)
    for p in patterns:
        clusters[_cluster_key(p)].append(p)
    return dict(clusters)


def _proposal_id(cluster_key: str) -> str:
    h = hashlib.sha1(cluster_key.encode()).hexdigest()[:8]
    kind = cluster_key.split("|")[0]
    return f"prop-{kind}-{h}"


def _scope_count(group: list[dict]) -> int:
    """How many distinct git branches this cluster's patterns came from.

    Per next-phase-design.md: a drift pattern that recurs across MULTIPLE scopes (branches) is a real
    regularity, not a single-branch accident — it is stronger evidence for a proposal. A cluster
    confined to one branch may just be that branch's local quirk.
    """
    branches = set()
    for p in group:
        sc = p.get("scope") or {}
        b = sc.get("branch")
        if b:
            branches.add(b)
    return len(branches)


def _build_proposal(cluster_key: str, group: list[dict], sources: set[str]) -> dict:
    """为一个聚类生成一条优化建议。"""
    parts = cluster_key.split("|")
    kind = parts[0]
    domain = parts[1] if len(parts) > 1 else ""
    root_file = parts[2] if len(parts) > 2 else ""
    copy_file = parts[3] if len(parts) > 3 else ""

    count = len(group)
    latest = max(p.get("ts", "") for p in group)

    # 根据 kind 决定建议类型和推荐操作
    if kind in {"scalar-sync", "reconcile_to_root"}:
        action = {
            "type": "add_scalar_sync_contract",
            "description": f"端口/参数漂移重复 {count} 次：`{root_file}` ↔ `{copy_file}`",
            "suggested_so_md_entry": {
                "domain": domain or f"auto:{root_file}",
                "root": root_file,
                "copies": [copy_file],
                "autofix": "scalar-sync",
                "pattern": _proposal_id(cluster_key),
                "reason": f"基于 {count} 次成功修复自动建议",
            },
        }
    elif kind in {"memory-conflict", "profile-drift", "memory-leak", "memory-superseded-chain"}:
        subject = ""
        for p in group:
            s = p.get("signature", {}).get("subject", "")
            if s:
                subject = s
                break
        action = {
            "type": "add_memory_condense_contract",
            "description": f"记忆漂移重复 {count} 次：subject=`{subject or domain}`",
            "suggested_so_md_entry": {
                "domain": domain or f"auto:{subject or 'memory'}",
                "root": root_file,
                "copies": [copy_file] if copy_file else [],
                "autofix": "memory-condense",
                "memory_subject": subject,
                "memory_target": f"memory/current/{subject or 'current'}.md",
                "pattern": _proposal_id(cluster_key),
                "reason": f"基于 {count} 次成功修复自动建议",
            },
        }
    elif kind in {"duplicate-block", "pointer-copy"}:
        action = {
            "type": "add_pointer_copy_contract",
            "description": f"重复块漂移重复 {count} 次",
            "suggested_so_md_entry": {
                "domain": domain or "auto:duplicate",
                "root": root_file,
                "copies": [copy_file] if copy_file else [],
                "autofix": "pointer-copy",
                "pattern": _proposal_id(cluster_key),
                "reason": f"基于 {count} 次成功修复自动建议",
            },
        }
    else:
        action = {
            "type": "add_detection_rule",
            "description": f"未知类型 `{kind}` 重复 {count} 次",
            "suggested_so_md_entry": {
                "domain": domain or f"auto:{kind}",
                "root": root_file,
                "copies": [copy_file] if copy_file else [],
                "pattern": _proposal_id(cluster_key),
                "reason": f"基于 {count} 次成功修复自动建议",
            },
        }

    return {
        "id": _proposal_id(cluster_key),
        "kind": kind,
        "domain": domain,
        "occurrences": count,
        "scope_count": _scope_count(group),  # distinct branches — higher = stronger cross-scope evidence
        "latest": latest,
        "sources": sorted(sources),
        "action": action,
        "status": "proposed",  # proposed | applied | skipped
    }


def analyze(target: pathlib.Path, min_occurrences: int = 3) -> list[dict]:
    """扫描状态目录，生成优化建议列表。"""
    state = target / ".context-gc"
    patterns = _load_jsonl(state / "patterns.jsonl")

    if not patterns:
        return []

    # 聚类
    clusters = _cluster(patterns)

    # 生成建议（只对出现次数 ≥ min_occurrences 的聚类）
    proposals = []
    for key, group in clusters.items():
        if len(group) < min_occurrences:
            continue
        # 收集来源（哪些 pattern 构成了这个聚类）
        sources = {p.get("id", "") for p in group if p.get("id")}
        proposals.append(_build_proposal(key, group, sources))

    # 按出现次数降序——最该被处理的最先
    proposals.sort(key=lambda p: p["occurrences"], reverse=True)
    return proposals


def _generate_so_md_entry(proposal: dict) -> str:
    """把一条建议翻译成 SOURCES.md domain 条目文本。"""
    entry = proposal.get("action", {}).get("suggested_so_md_entry", {})
    if not entry:
        return ""

    name = entry.get("domain", "auto")
    root = entry.get("root", "")
    copies = entry.get("copies", [])
    autofix = entry.get("autofix", "")
    reason = entry.get("reason", "")
    pattern = entry.get("pattern", "")

    lines = [
        f"### `{name}` — auto-generated from pattern analysis",
        "",
        f"- **Root:** `{root}`",
        "- **Owner:** `auto`",
        "- **Risk:** `low`",
        "- **Copies:**",
    ]
    for c in copies:
        lines.append(f"  - `{c}` — detected copy")
    if autofix:
        lines.append(f"- **Auto-fix:** `{autofix}`")
    if pattern:
        lines.append(f"- **Pattern:** `{pattern}`")
    lines.append("- **Status:** `NOT_CHECKED`")
    lines.append(f"- **Reason:** {reason}")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def cmd_apply(target: pathlib.Path, proposal_id: str) -> int:
    """应用一条建议：把建议翻译成 SOURCES.md 条目，追加到文件末尾。"""
    proposals_path = target / ".context-gc" / "optimization-proposals.json"
    if not proposals_path.exists():
        print("No optimization proposals found. Run analyze first.")
        return 1

    proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
    match = next((p for p in proposals.get("proposals", []) if p["id"] == proposal_id), None)
    if not match:
        print(f"Proposal `{proposal_id}` not found.")
        return 2

    so_path = target / "SOURCES.md"
    if not so_path.exists():
        print("SOURCES.md not found. Run init first.")
        return 3

    entry_text = _generate_so_md_entry(match)
    if not entry_text:
        print(f"Proposal `{proposal_id}` has no SOURCES.md entry to generate.")
        return 4

    # 检查是否已存在同名 domain
    existing = so_path.read_text(encoding="utf-8")
    domain_name = match.get("action", {}).get("suggested_so_md_entry", {}).get("domain", "")
    if domain_name and f"### `{domain_name}`" in existing:
        print(f"Domain `{domain_name}` already exists in SOURCES.md. Skipping.")
        return 0

    # 追加到 SOURCES.md 末尾
    so_path.write_text(existing.rstrip() + "\n\n" + entry_text, encoding="utf-8")

    # 标记建议已应用
    match["status"] = "applied"
    proposals["proposals"] = [p if p["id"] != proposal_id else match for p in proposals["proposals"]]
    proposals_path.write_text(json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8")

    # 写审计日志
    (target / ".context-gc" / "decisions.jsonl").open("a", encoding="utf-8").write(
        json.dumps({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "item": proposal_id,
            "kind": "hill-climb-apply",
            "choice": 0,
            "action": {"op": "add_so_md_entry", "domain": domain_name},
            "by": "human",
            "policy_level": "hill-climb",
            "applied": True,
            "detail": f"Applied optimization proposal: {match.get('action', {}).get('description', '')}",
            "reversible": True,
        }, ensure_ascii=False) + "\n"
    )

    print(f"✓ Proposal `{proposal_id}` applied: {match.get('action', {}).get('description', '')}")
    print(f"  Domain `{domain_name}` added to SOURCES.md")
    return 0


def _candidate_eval(proposal: dict) -> dict:
    """把一条 proposal 翻译成一个候选 eval（供 evol 闭环用）。

    候选 eval 描述"agent 遇到这类反复出现的漂移该怎么处理"。它带门控元数据，但**绝不**自动进
    evals.json——按 next-phase-design.md 的死命令：自动生成可以，自动合并不行。一个候选要进集合，
    必须满足 (a) 跨 ≥2 scope (b) samples≥3 共识下 SKILL 稳定失败 (c) 人审一次。这里只产 (a) 的标记，
    (b)(c) 由 evol 闭环的后续步骤把关。
    """
    kind = proposal.get("kind", "drift")
    entry = proposal.get("action", {}).get("suggested_so_md_entry", {})
    root = entry.get("root", "")
    copies = entry.get("copies", [])
    copy = copies[0] if copies else ""
    occ = proposal.get("occurrences", 0)
    scope_count = proposal.get("scope_count", 0)

    return {
        "candidate_id": f"evol-{proposal.get('id', kind)}",
        "name": f"evol-{kind}-recurring",
        "source": "evol",
        "occurrences": occ,
        "scope_count": scope_count,
        # 门控元数据：闭环后续步骤读这些字段判断该不该让候选进集合
        "gate": {
            "cross_scope_ok": scope_count >= 2,         # (a) 跨分支重复才是真规律
            "needs_consensus_check": True,               # (b) 待 samples≥3 验证 SKILL 是否真失败
            "needs_human_review": True,                  # (c) 待人审 staging
        },
        "draft_eval": {
            "prompt": f"You are an autonomous agent. context-gc has seen `{kind}` drift between `{root}` and `{copy}` recur {occ} time(s) across {scope_count} branch(es). You just touched `{root}` again. Decide what to do.",
            "expected_output": f"The agent recognizes this is a recurring `{kind}` pattern (already seen {occ}x), proactively checks `{copy}` against `{root}` without being told, and proposes recording it as a SOURCES.md contract so the recurrence stops. Requires confirmation before any sweep.",
            "assertions": [
                f"Recognizes `{kind}` between `{root}` and `{copy}` as a recurring pattern",
                "Proactively checks the copy against the root without being told",
                "Proposes a SOURCES.md contract to stop the recurrence",
                "Requires confirmation before editing; mentions SOURCES.md write barrier",
            ],
        },
    }


def cmd_emit_eval(target: pathlib.Path, min_occurrences: int) -> int:
    """从重复 pattern 生成候选 eval → .context-gc/candidate-evals.json（只生成，不合并）。"""
    proposals = analyze(target, min_occurrences)
    candidates = [_candidate_eval(p) for p in proposals]
    state = target / ".context-gc"
    state.mkdir(exist_ok=True)
    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "target": target.name,
        "candidate_count": len(candidates),
        "note": "候选 eval，未进 evals.json。进集合需：跨≥2 scope + samples≥3 共识下 SKILL 稳定失败 + 人审。",
        "candidates": candidates,
    }
    out_path = state / "candidate-evals.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if not candidates:
        print(f"# evol · 无候选 eval（没有 pattern 重复 ≥ {min_occurrences} 次）")
        return 0
    ready = [c for c in candidates if c["gate"]["cross_scope_ok"]]
    print(f"# evol · {len(candidates)} 个候选 eval（{len(ready)} 个已满足跨 scope 门槛）")
    for c in candidates:
        mark = "✓跨scope" if c["gate"]["cross_scope_ok"] else "·单scope"
        print(f"  [{mark}] {c['name']}: 出现 {c['occurrences']}x / {c['scope_count']} 分支")
    print(f"\n候选写入 {out_path.relative_to(target)} — 未进 evals.json（需共识验证 + 人审）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Layer 4 Hill Climbing — analyze drift patterns and suggest optimizations")
    ap.add_argument("--target", default=".")
    ap.add_argument("--min-occurrences", type=int, default=3, help="minimum cluster size to generate a proposal (default: 3)")
    ap.add_argument("--apply", help="apply a specific proposal by ID")
    ap.add_argument("--emit-eval", action="store_true",
                    help="generate candidate evals from recurring patterns → candidate-evals.json (does NOT merge into evals.json)")
    ap.add_argument("--json-only", action="store_true", help="print only the proposals JSON path")
    args = ap.parse_args()

    target = pathlib.Path(args.target).resolve()
    if not target.is_dir():
        print(f"FAIL: target is not a directory: {target}")
        return 1

    state = target / ".context-gc"
    state.mkdir(exist_ok=True)

    # --apply: 应用一条建议
    if args.apply:
        return cmd_apply(target, args.apply)

    # --emit-eval: 从重复 pattern 生成候选 eval（只生成不合并）
    if args.emit_eval:
        return cmd_emit_eval(target, args.min_occurrences)

    # 分析
    proposals = analyze(target, args.min_occurrences)

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "target": target.name,
        "min_occurrences": args.min_occurrences,
        "total_patterns": len(_load_jsonl(state / "patterns.jsonl")),
        "proposal_count": len(proposals),
        "proposals": proposals,
    }
    out_path = state / "optimization-proposals.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_only:
        print(str(out_path))
        return 0

    if not proposals:
        print("# 爬坡分析 · 无需优化")
        print()
        print(f"  已积累 {out['total_patterns']} 个 pattern，但还没有同类型模式重复 ≥ {args.min_occurrences} 次。")
        print("  继续使用，pattern 积累够多时会自动产生建议。")
        return 0

    print(f"# 爬坡分析 · {len(proposals)} 条优化建议")
    print(f"  共 {out['total_patterns']} 个 pattern，{len(proposals)} 个聚类达到 ≥ {args.min_occurrences} 次")
    print()
    for i, p in enumerate(proposals, 1):
        act = p["action"]
        print(f"## [{i}] {p['id']}")
        print(f"  类型: {p['kind']}")
        print(f"  出现: {p['occurrences']} 次（最近: {p['latest']}）")
        print(f"  建议: {act['type']} — {act['description']}")
        print(f"  操作: python scripts/analyze_patterns.py --target . --apply {p['id']}")
        print()

    print(f"详细方案见: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
