#!/usr/bin/env python3
"""context-gc mark — the deterministic half of MARK.

This runs the mechanical checks that do not need judgment, and emits candidates for the model to
adjudicate. It NEVER edits anything. Three checks:

  1. orphan-reference : a relative file/path mentioned in a context file that does not exist on disk
  2. duplicate-block  : an identical non-trivial line repeated across multiple context files
  3. stale-doc        : a doc whose git mtime is much older than code it appears to describe (best effort)

Output:
  - .context-gc/findings.json  machine-readable (for CI / dashboards)
  - stdout                     a human entropy report

Judgment (is this really garbage? which is root? FORK or HISTORICAL?) stays with the model. This
runner only narrows the search so the model spends tokens on decisions, not grep.

Usage:
  python scripts/mark.py --target /path/to/repo
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DEFAULT_EXCLUDES,
    git_last_commit_epoch,
    iter_agent_context_files,
    iter_context_files,
    memory_status,
    memory_subject,
    memory_type,
    rough_token_count,
    skill_names,
)

# Orphan check follows only genuine markdown links: [text](target). Backtick code spans are inline
# code/examples/globs by convention, not navigable references — flagging them produces noise, as the
# first dogfood run on this very repo proved. A real link checker checks links, not code spans.
REF_RE = re.compile(r"]\(([^)]+)\)")
URL_RE = re.compile(r"^[a-z]+://|^mailto:", re.I)
TRIVIAL = re.compile(r"^[\s#>*\-=|`._]*$")
# Skip runtime/generated state and template placeholders — they are not committed files.
SKILL_REF_RE = re.compile(r"(?:skills/)?([a-z][a-z0-9_-]{2,})")
INSTRUCTION_RE = re.compile(
    r"\b(must|always|never|use|limit|prefer|avoid|cap|should|不得|必须|总是|不要|优先|避免)\b|\d+\s*(req/s|rps|seconds?|tokens?|lines?)",
    re.I,
)
DATE_STEM_RE = re.compile(r"[-_]?20\d{2}[-_]?(?:0\d|1[0-2])[-_]?(?:[0-3]\d)?")
TONE_GROUPS = {
    "brevity": {"concise", "brief", "terse", "short", "简洁", "简短"},
    "detail": {"detailed", "explain", "step-by-step", "thorough", "verbose", "详细", "解释"},
    "warmth": {"warm", "friendly", "empathetic", "casual", "温暖", "友好"},
    "direct": {"direct", "blunt", "no-nonsense", "直接"},
}
POLICY_KEYWORDS = {
    "rate-limit": {"rate", "req/s", "rps", "scrap", "crawl", "limit", "cap", "请求"},
    "model": {"model", "opus", "sonnet", "haiku", "claude", "模型"},
    "tests": {"test", "pytest", "validate", "ci", "测试"},
    "deploy": {"deploy", "release", "ship", "发布", "部署"},
    "tone": set().union(*TONE_GROUPS.values()),
}
MEMORY_CONFLICT_PAIRS = [("concise", "verbose"), ("concise", "detailed"), ("brief", "step-by-step"), ("direct", "warm")]
def _rel(target: pathlib.Path, path: pathlib.Path) -> str:
    return path.relative_to(target).as_posix()


def _read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_excludes(target: pathlib.Path) -> list[str]:
    cfg = target / ".context-gc" / "config.yml"
    if not cfg.exists():
        return DEFAULT_EXCLUDES
    excludes: list[str] = []
    in_exclude = False
    for line in cfg.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("exclude:"):
            in_exclude = True
            continue
        if in_exclude:
            if s.startswith("- "):
                excludes.append(s[2:].strip().strip('"'))
            elif s and not s.startswith("#") and not line.startswith(" "):
                break
    # Merge config excludes ON TOP of the defaults — never drop the baseline (.git, node_modules,
    # outputs, etc.). A user adding one custom exclude must not silently lose all built-in ones.
    return sorted(set(DEFAULT_EXCLUDES) | set(excludes))


def _dirty_files(target: pathlib.Path, excludes: list[str]) -> list[pathlib.Path]:
    dirty = target / ".context-gc" / "dirty.jsonl"
    if not dirty.exists():
        return []
    paths = []
    all_context = {_rel(target, p): p for p in iter_context_files(target, excludes)}
    for line in dirty.read_text(encoding="utf-8").splitlines():
        try:
            rel = json.loads(line).get("path")
        except Exception:
            continue
        if not rel:
            continue
        rel = str(rel).replace("\\", "/")
        path = all_context.get(rel) or (target / rel)
        if path.exists() and path.is_file():
            paths.append(path)
    # Agent roots influence all agent checks; include them when any agent file is dirty.
    roots = [target / name for name in ("CLAUDE.md", "SOUL.md") if (target / name).exists()]
    if any("/memory/" in f"/{_rel(target, p)}" or "/skills/" in f"/{_rel(target, p)}" or p.name in {"CLAUDE.md", "SOUL.md"} for p in paths):
        paths.extend(roots)
    return sorted(set(paths))


def _line_records(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    records = []
    for path in files:
        rel = _rel(target, path)
        text = _read_text(path)
        for idx, raw in enumerate(text.splitlines(), 1):
            line = raw.strip(" -*#>\t")
            if len(line) < 12 or not INSTRUCTION_RE.search(line):
                continue
            records.append({"file": rel, "line": idx, "text": line, "norm": _norm(line)})
    return records


def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\d+", "<num>", text)
    text = re.sub(r"[^a-z0-9_\-< >/一-鿿]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _policy_domain(text: str) -> str | None:
    low = text.lower()
    for domain, words in POLICY_KEYWORDS.items():
        if any(w in low for w in words):
            return domain
    return None


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", text)


def check_dead_skill_refs(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    existing = skill_names(target)
    if not existing:
        return []
    findings = []
    skip = {
        "agent", "claude", "collection", "context-gc", "github", "markdown", "memory", "name",
        "needed", "python", "review", "scraping", "skill", "skills", "source", "synthesis", "this",
        "use", "when",
    }
    for path in files:
        rel = _rel(target, path)
        if pathlib.PurePath(rel).parts and pathlib.PurePath(rel).parts[0] == "skills":
            continue
        text = _read_text(path)
        for idx, line in enumerate(text.splitlines(), 1):
            names = set(re.findall(r"skills/([a-z][a-z0-9_-]{2,})", line))
            names.update(re.findall(r"\b([a-z][a-z0-9_-]{2,}-skill)\b", line))
            if "skill" in line.lower():
                names.update(re.findall(r"\b([a-z][a-z0-9_-]{2,})\b", line))
            for name in sorted(names):
                if name in existing or name in skip or len(name) < 4:
                    continue
                if (target / "skills" / name / "SKILL.md").exists():
                    continue
                findings.append({
                    "type": "dead-skill-ref",
                    "status": "DRIFTED",
                    "severity": "high",
                    "file": rel,
                    "line": idx,
                    "detail": f"mentions `{name}` as a skill-like reference, but `skills/{name}/SKILL.md` is missing",
                    "needs_judgment": "Confirm whether the skill was renamed or retired, then repoint or delete the instruction.",
                })
    return findings[:25]


def check_agent_instruction_clusters(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    records = _line_records(target, files)
    grouped: dict[str, list[dict]] = {}
    for rec in records:
        domain = _policy_domain(rec["text"])
        if not domain:
            continue
        grouped.setdefault(domain, []).append(rec)

    findings = []
    for domain, items in grouped.items():
        locs = {item["file"] for item in items}
        if len(items) < 2 or len(locs) < 2:
            continue
        nums = {tuple(_numbers(item["text"])) for item in items if _numbers(item["text"])}
        modals = {"never" if re.search(r"\bnever\b|不要|不得", item["text"], re.I) else "positive" for item in items}
        conflict = len(nums) > 1 or len(modals) > 1
        examples = "; ".join(f"{item['file']}:{item['line']} `{item['text'][:60]}`" for item in items[:3])
        findings.append({
            "type": "semantic-instruction-cluster",
            "status": "DRIFTED" if conflict else "UNKNOWN_ROOT",
            "severity": "high" if conflict else "medium",
            "files": sorted(locs),
            "detail": f"{domain} instructions overlap across agent context: {examples}",
            "needs_judgment": "Choose one authoritative agent policy and replace other copies with pointers; do not auto-merge.",
        })
    return findings[:25]


def check_memory_leak(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    memory_files = [p for p in files if "memory" in pathlib.PurePath(_rel(target, p)).parts]
    if not memory_files:
        return []
    stems: dict[str, list[str]] = {}
    total_tokens = 0
    for path in memory_files:
        rel = _rel(target, path)
        total_tokens += rough_token_count(_read_text(path))
        stem = DATE_STEM_RE.sub("", path.stem).strip("-_") or path.stem
        stems.setdefault(stem, []).append(rel)
    findings = []
    repeated = {stem: rels for stem, rels in stems.items() if len(rels) >= 3}
    if len(memory_files) >= 20 or total_tokens >= 8000 or repeated:
        detail = f"memory heap has {len(memory_files)} file(s), ~{total_tokens} tokens"
        if repeated:
            first = next(iter(repeated.items()))
            detail += f"; repeated dated stem `{first[0]}` appears in {len(first[1])} files"
        findings.append({
            "type": "memory-leak",
            "status": "NOT_CHECKED",
            "severity": "low" if len(memory_files) < 20 else "medium",
            "files": [_rel(target, p) for p in memory_files[:12]],
            "detail": detail,
            "needs_judgment": "Condense append-only memories into current facts, preserving evidence or history where needed.",
        })
    return findings


def check_memory_drift(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    memory_files = [p for p in files if "memory" in pathlib.PurePath(_rel(target, p)).parts]
    if not memory_files:
        return []
    by_subject: dict[str, list[dict]] = {}
    total_tokens = 0
    for path in memory_files:
        text = _read_text(path)
        total_tokens += rough_token_count(text)
        rec = {
            "path": path,
            "rel": _rel(target, path),
            "text": text,
            "subject": memory_subject(path, text),
            "type": memory_type(path, text),
            "status": memory_status(text),
        }
        by_subject.setdefault(rec["subject"], []).append(rec)
    findings = []
    for subject, items in by_subject.items():
        if len(items) >= 3 or any(item["status"] == "superseded" for item in items):
            findings.append({
                "type": "memory-superseded-chain",
                "status": "NOT_CHECKED",
                "severity": "low",
                "files": [item["rel"] for item in items[:12]],
                "detail": f"memory subject `{subject}` has {len(items)} variant(s) or superseded markers",
                "needs_judgment": "Condense to one current memory with evidence pointers; preserve or archive old variants.",
            })
        joined = "\n".join(item["text"].lower() for item in items)
        for a, b in MEMORY_CONFLICT_PAIRS:
            if a in joined and b in joined:
                findings.append({
                    "type": "memory-conflict",
                    "status": "UNKNOWN_ROOT",
                    "severity": "medium",
                    "files": [item["rel"] for item in items[:12]],
                    "detail": f"memory subject `{subject}` contains potentially conflicting cues `{a}` and `{b}`",
                    "needs_judgment": "Choose current truth or write uncertainty; do not silently overwrite profile or long-term memory.",
                })
                break
        types = {item["type"] for item in items}
        if "profile" in types and len(types) > 1:
            findings.append({
                "type": "profile-drift",
                "status": "UNKNOWN_ROOT",
                "severity": "medium",
                "files": [item["rel"] for item in items[:12]],
                "detail": f"profile memory and other memory layers both describe `{subject}`",
                "needs_judgment": "Reconcile profile vs long/mid-term memory into a current profile fact or scoped exception.",
            })
        for item in items:
            if item["type"] == "mid-term" and re.search(r"\b(done|completed|cancelled|superseded|abandoned)\b|完成|取消|废弃", item["text"], re.I):
                findings.append({
                    "type": "midterm-expired",
                    "status": "NOT_CHECKED",
                    "severity": "low",
                    "file": item["rel"],
                    "detail": "mid-term memory appears completed/cancelled/superseded",
                    "needs_judgment": "Archive or mark superseded after confirming it is no longer active.",
                })
    if total_tokens >= 8000 or len(memory_files) >= 20:
        findings.append({
            "type": "memory-budget",
            "status": "NOT_CHECKED",
            "severity": "medium",
            "files": [_rel(target, p) for p in memory_files[:12]],
            "detail": f"memory heap has {len(memory_files)} file(s), ~{total_tokens} tokens",
            "needs_judgment": "Compact memory before adding more durable facts.",
        })
    return findings[:30]


def check_skill_bloat(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    skill_files = [p for p in files if "skills" in pathlib.PurePath(_rel(target, p)).parts and p.name == "SKILL.md"]
    if not skill_files:
        return []
    sizes = sorted(((rough_token_count(_read_text(p)), _rel(target, p)) for p in skill_files), reverse=True)
    findings = []
    large = [(tokens, rel) for tokens, rel in sizes if tokens >= 2000]
    if len(skill_files) >= 15 or large:
        detail = f"agent has {len(skill_files)} skill file(s); largest: " + ", ".join(f"{rel} (~{tokens} tokens)" for tokens, rel in sizes[:3])
        findings.append({
            "type": "skill-bloat",
            "status": "NOT_CHECKED",
            "severity": "medium" if len(skill_files) >= 15 else "low",
            "files": [rel for _, rel in sizes[:12]],
            "detail": detail,
            "needs_judgment": "Review for overlapping or rarely-used skills; archive/freeze only after confirmation.",
        })
    return findings


def check_tone_behavior_drift(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    hits: dict[str, list[str]] = {k: [] for k in TONE_GROUPS}
    for path in files:
        rel = _rel(target, path)
        text = _read_text(path)
        for idx, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            for group, words in TONE_GROUPS.items():
                if any(w in low for w in words):
                    hits[group].append(f"{rel}:{idx} `{line.strip()[:70]}`")
    findings = []
    pairs = [("brevity", "detail"), ("warmth", "direct")]
    for a, b in pairs:
        if hits[a] and hits[b]:
            findings.append({
                "type": "tone-behavior-drift",
                "status": "UNKNOWN_ROOT",
                "severity": "medium",
                "files": sorted({h.split(":", 1)[0] for h in hits[a] + hits[b]}),
                "detail": f"agent behavior instructions may clash: {hits[a][0]} ↔ {hits[b][0]}",
                "needs_judgment": "Pick the root tone/behavior policy and compact the losing instructions into a pointer or exception.",
            })
    return findings


def context_budget_findings(target: pathlib.Path, files: list[pathlib.Path]) -> tuple[list[dict], list[str]]:
    groups = {"agent-roots": 0, "skills": 0, "memory": 0, "other-context": 0}
    for path in files:
        rel = _rel(target, path)
        text = _read_text(path)
        parts = set(pathlib.PurePath(rel).parts)
        if path.name in {"CLAUDE.md", "SOUL.md"}:
            group = "agent-roots"
        elif "skills" in parts:
            group = "skills"
        elif "memory" in parts:
            group = "memory"
        else:
            group = "other-context"
        groups[group] += rough_token_count(text)
    total = sum(groups.values())
    lines = ["", "## Context budget", "", f"Approximate context tokens across scanned files: {total}"]
    for group, tokens in groups.items():
        if tokens:
            lines.append(f"- {group}: ~{tokens} tokens")
    findings = []
    if groups["agent-roots"] + groups["skills"] + groups["memory"] >= 12000:
        findings.append({
            "type": "context-budget",
            "status": "NOT_CHECKED",
            "severity": "medium",
            "detail": f"agent context budget is ~{groups['agent-roots'] + groups['skills'] + groups['memory']} tokens",
            "needs_judgment": "Compact agent roots, skills, or memory before adding more persistent instructions.",
        })
    return findings, lines


def check_orphans(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    findings = []
    for path in files:
        rel = path.relative_to(target).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in REF_RE.finditer(text):
            ref = (m.group(1) or m.group(2) or "").strip()
            if not ref or URL_RE.search(ref) or ref.startswith("#"):
                continue
            ref_clean = ref.split("#", 1)[0].split("?", 1)[0]
            if not ref_clean or ref_clean.startswith("<") or "{" in ref_clean or " " in ref_clean:
                continue
            if not re.search(r"\.[A-Za-z0-9]{1,5}$", ref_clean):
                continue
            candidates = [
                (target / ref_clean),
                (path.parent / ref_clean),
            ]
            if any(c.exists() for c in candidates):
                continue
            line_no = text[: m.start()].count("\n") + 1
            findings.append({
                "type": "orphan-reference",
                "status": "DRIFTED",
                "severity": "high",
                "file": rel,
                "line": line_no,
                "detail": f"references `{ref_clean}` which does not exist on disk",
                "needs_judgment": "Confirm the target was renamed/removed, then repoint or delete.",
            })
    return findings


def check_duplicates(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    seen: dict[str, list[str]] = {}
    for path in files:
        rel = path.relative_to(target).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if len(line) < 40 or TRIVIAL.match(line):
                continue
            seen.setdefault(line, [])
            if rel not in seen[line]:
                seen[line].append(rel)
    findings = []
    for line, locs in seen.items():
        if len(locs) >= 3:
            findings.append({
                "type": "duplicate-block",
                "status": "UNKNOWN_ROOT",
                "severity": "medium",
                "files": sorted(locs),
                "detail": f"identical line repeated in {len(locs)} files: \"{line[:80]}\"",
                "needs_judgment": "Pick one root, replace the rest with pointers. A drift factory even if copies agree now.",
            })
    return sorted(findings, key=lambda f: -len(f["files"]))[:25]


def check_stale(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    now = int(time.time())
    findings = []
    for path in files:
        rel = path.relative_to(target).as_posix()
        if path.suffix.lower() not in {".md", ".mdx"}:
            continue
        epoch = git_last_commit_epoch(target, rel)
        if epoch is None:
            continue
        age_days = (now - epoch) / 86400
        if age_days > 365:
            findings.append({
                "type": "stale-doc",
                "status": "NOT_CHECKED",
                "severity": "low",
                "file": rel,
                "detail": f"not touched in git for ~{int(age_days)} days; verify it still matches its root",
                "needs_judgment": "Old docs are suspects, not garbage. Confirm against current code before any edit.",
            })
    return sorted(findings, key=lambda f: f["file"])[:25]


SEV_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}


def render_report(target_name: str, findings: list[dict], n_files: int, extra_sections: list[str] | None = None) -> str:
    lines = [f"## Entropy report — {target_name} (mechanical MARK)", ""]
    lines.append(f"Scanned {n_files} context-bearing files. {len(findings)} candidate(s) for review.")
    lines.append("Status legend: SYNCED | DRIFTED | NOT_CHECKED | FORK | HISTORICAL | UNKNOWN_ROOT")
    lines.append("")
    if not findings:
        lines.append("No mechanical drift candidates. (Judgment-level checks still need a human/model pass.)")
    else:
        for f in findings:
            icon = SEV_ICON.get(f["severity"], "•")
            where = f.get("file") or ", ".join(f.get("files", []))
            loc = f":{f['line']}" if f.get("line") else ""
            lines.append(f"{icon} {f['type'].upper():28} {f['status']:12} {where}{loc}")
            lines.append(f"     {f['detail']}")
            lines.append(f"     → {f['needs_judgment']}")
        lines.append("")
        lines.append("These are CANDIDATES. The model/user must decide root, FORK vs HISTORICAL, and any SWEEP.")
    if extra_sections:
        lines.extend(extra_sections)
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic mechanical MARK for context-gc")
    ap.add_argument("--target", default=".", help="repository to scan (default: cwd)")
    ap.add_argument("--dirty-only", action="store_true", help="scan only files listed in .context-gc/dirty.jsonl")
    ap.add_argument("--report-out", help="write the markdown report to this path as well as stdout")
    ap.add_argument("--json-only", action="store_true", help="print only the findings.json path")
    a = ap.parse_args()

    target = pathlib.Path(a.target).resolve()
    if not target.is_dir():
        print(f"FAIL: target is not a directory: {target}")
        return 1

    excludes = _load_excludes(target)
    all_files = list(iter_context_files(target, excludes))
    files = _dirty_files(target, excludes) if a.dirty_only else all_files
    if a.dirty_only and not files:
        files = []
    agent_files = list(iter_agent_context_files(target, excludes))
    if a.dirty_only:
        dirty_rels = {_rel(target, p) for p in files}
        agent_files = [p for p in agent_files if _rel(target, p) in dirty_rels or p.name in {"CLAUDE.md", "SOUL.md"}]

    findings = (
        check_orphans(target, files)
        + check_duplicates(target, files)
        + check_stale(target, files)
        + check_dead_skill_refs(target, agent_files)
        + check_agent_instruction_clusters(target, agent_files)
        + check_memory_leak(target, agent_files)
        + check_memory_drift(target, agent_files)
        + check_skill_bloat(target, agent_files)
        + check_tone_behavior_drift(target, agent_files)
    )
    budget_findings, budget_lines = context_budget_findings(target, all_files)
    findings += budget_findings
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: order.get(f["severity"], 9))

    state_dir = target / ".context-gc"
    state_dir.mkdir(exist_ok=True)
    out = state_dir / "findings.json"
    out.write_text(json.dumps({
        "target": target.name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dirty_only": a.dirty_only,
        "files_scanned": len(files),
        "findings": findings,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    report = render_report(target.name, findings, len(files), budget_lines)
    if a.report_out:
        report_path = pathlib.Path(a.report_out)
        if not report_path.is_absolute():
            report_path = target / report_path
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

    if a.json_only:
        print(out)
        return 0

    print(report)
    print(f"[findings.json] {out.relative_to(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
