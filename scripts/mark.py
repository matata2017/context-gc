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
    _excluded,
    current_scope,
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


# A command that invokes a script by path — `python tools/build.py`, `bash scripts/run.sh`. Captures
# the first path-like argument of a known interpreter, so we check the invoked script (not its args).
CMD_REF_RE = re.compile(
    r"\b(?:python3?|node|bash|sh|ruby|deno|ts-node|go run|pytest|php|perl)\s+([A-Za-z0-9_][\w\-./]*\.[A-Za-z0-9]+)"
)
CMD_PLACEHOLDER_RE = re.compile(r"path/to|your[-_]|/example|<[^>]+>|\.\.\.|YOUR|\$\{", re.I)


def check_orphan_command_refs(target: pathlib.Path, files: list[pathlib.Path]) -> list[dict]:
    """Orphan in a COMMAND — a script path invoked in a doc that does not exist on disk.

    `check_orphans` follows markdown links `[](path)` only; a script path inside a fenced command
    (`python junli-ai-novel/scripts/check.py`) is invisible to it. Yet that is the most damaging
    stale-doc form: the doc keeps 'teaching' a toolchain a refactor deleted, so the workflow fails
    silently every run. Found on a real novel repo where 4 such commands across 3 docs all pointed at
    scripts that no longer existed — 100% missed by every other check. Kept narrow to control noise:
    only the invoked script of a known interpreter, must have a directory + extension, and not a URL /
    absolute path / placeholder. Severity rises when the same dead path is taught in 2+ docs.
    """
    seen: dict[str, list[str]] = {}
    for path in files:
        if path.suffix.lower() not in {".md", ".mdx"}:
            continue
        rel = _rel(target, path)
        # SOURCES.md contains re-check commands (e.g. `python scripts/mark.py`) that are
        # governance directives, not project toolchain references.  Skipping it avoids a
        # false positive every time init_context_gc writes a re-check for a context-gc script
        # that does not live in the target project.
        if rel.lower() == "sources.md":
            continue
        text = _read_text(path)
        for m in CMD_REF_RE.finditer(text):
            ref = m.group(1)
            if "/" not in ref or URL_RE.search(ref) or ref.startswith("/") or CMD_PLACEHOLDER_RE.search(ref):
                continue
            if (target / ref).exists() or (path.parent / ref).exists():
                continue
            seen.setdefault(ref, [])
            if rel not in seen[ref]:
                seen[ref].append(rel)
    findings = []
    for ref, locs in sorted(seen.items()):
        findings.append({
            "type": "orphan-command-ref",
            "status": "DRIFTED",
            "severity": "medium" if len(locs) >= 2 else "low",
            "files": sorted(locs),
            "detail": f"command invokes `{ref}`, which does not exist (taught in {len(locs)} doc(s)); a refactor likely moved or deleted it",
            "needs_judgment": f"Does `{ref}`'s toolchain still exist under another path? Repoint the command, or mark the step retired — until then the doc teaches a command that fails every run.",
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


# NOTE: a `check_stale` based on absolute git age (">365 days untouched") was removed after a real-repo
# audit (httpie/cli) showed it false-positived on 24/26 findings — every stable governance doc
# (CODE_OF_CONDUCT, AUTHORS, LICENSE, CHANGELOG, ISSUE_TEMPLATEs) got flagged. "Old" is not "stale":
# a doc is stale only relative to the code it describes. That relative signal is `check_spec_drift_candidates`
# (code root git-newer than its doc copy); overdue re-verification is `check_stale_verification` (TTL on a
# declared domain); an undeclared doc is `check_coverage_gaps`. Absolute age added only noise, so it's gone.
CODE_SUFFIXES = {".py", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".c", ".cpp", ".sh", ".php"}


def check_spec_drift_candidates(target: pathlib.Path) -> list[dict]:
    """SPEC_DRIFT trigger — when a code root commits AFTER a doc that describes it, prompt judgment.

    The blind spot this fills: "the doc says X, the code now does Y" is real drift the mechanical
    checks (value/link/duplicate) cannot see — it needs reading code + reading prose + judging whether
    they agree. context-gc designs that as a JUDGMENT step, but nothing TRIGGERED it. This connects the
    two: it reads SOURCES.md's declared root→copy pairs, and when a CODE root is git-newer than a DOC
    copy that documents it, it raises a NEEDS_JUDGMENT candidate — NOT a mechanical verdict of drift,
    but a prompt: "the code moved, go re-check whether this doc still describes it." Reuses the existing
    SOURCES.md declaration + git mtime; adds no new heuristic that could false-positive on content.
    """
    src = target / "SOURCES.md"
    if not src.exists():
        return []
    try:
        import minor_gc
        domains = minor_gc.parse_sources(src)
    except Exception:
        return []
    findings = []
    for domain in domains:
        root = (domain.root or "").strip()
        if not root or pathlib.PurePath(root).suffix.lower() not in CODE_SUFFIXES:
            continue  # only code roots: doc-vs-code drift, not doc-vs-doc
        if domain.status in {"FORK", "HISTORICAL", "UNKNOWN_ROOT"}:
            continue  # those are deliberate or unresolved; don't nag
        root_epoch = git_last_commit_epoch(target, root)
        if root_epoch is None:
            continue
        for copy in domain.copies:
            copy = copy.strip()
            if pathlib.PurePath(copy).suffix.lower() not in {".md", ".mdx"}:
                continue  # only doc copies need the "still accurate?" judgment
            copy_epoch = git_last_commit_epoch(target, copy)
            if copy_epoch is None or root_epoch <= copy_epoch:
                continue  # doc is same-age-or-newer → presumed in sync
            findings.append({
                "type": "spec-drift-candidate",
                "status": "NEEDS_JUDGMENT",
                "severity": "medium",
                "file": copy,
                "detail": f"code root `{root}` committed after this doc; the doc may describe stale behavior",
                "needs_judgment": f"Read `{root}` and `{copy}`: does the doc still accurately describe what the code does? This is a prompt to judge, not a verdict — only update after confirming a real mismatch.",
            })
    return findings


# Top-level, user-facing docs that SHOULD be in the governance map. A file matching one of these and
# NOT declared in any SOURCES.md domain is a coverage gap — the map itself drifted. Deliberately
# narrow: only install/onboarding/top-level docs, not every .md (demos, references, research are
# internal and would be noise). This is the meta-check: is the authority map itself complete?
GOVERNABLE_TOPLEVEL = re.compile(
    r"^(README[^/]*\.md|INSTALL[^/]*\.md|CONTRIBUTING\.md|CLAUDE\.md|SOUL\.md|AGENTS?\.md"
    r"|install\.(py|sh|ps1)|scripts/install\.(sh|ps1))$",
    re.I,
)


def check_coverage_gaps(target: pathlib.Path) -> list[dict]:
    """Meta-check — find context files the authority map (SOURCES.md) forgot to declare.

    The systemic problem behind a string of one-off blind spots (INSTALL_AGENT.md, install.py, the
    Chinese README all slipped through): context-gc can only govern what SOURCES.md declares, but the
    map is hand-written once and silently goes out of date as files are added. This is meta-drift —
    the governance map drifts from the set of files that actually need governing.

    Rather than patch each undeclared file by hand (whack-a-mole), this surfaces them: any top-level /
    onboarding doc that is NOT a root or copy in any SOURCES domain is flagged NEEDS_JUDGMENT —
    "should this be governed, and under which root?". A prompt to complete the map, not a verdict.
    Narrow on purpose (GOVERNABLE_TOPLEVEL) so it points at real gaps, not internal demo/reference files.
    """
    src = target / "SOURCES.md"
    if not src.exists():
        return []
    try:
        import minor_gc
        domains = minor_gc.parse_sources(src)
    except Exception:
        return []
    declared = set()
    for d in domains:
        if d.root:
            declared.add(d.root.strip().rstrip("/"))
        for c in d.copies:
            declared.add(c.strip())
    findings = []
    for rel_path in sorted(_governable_toplevel_files(target)):
        if rel_path in declared:
            continue
        findings.append({
            "type": "coverage-gap",
            "status": "NEEDS_JUDGMENT",
            "severity": "low",
            "file": rel_path,
            "detail": "a top-level/onboarding file not declared in any SOURCES.md domain — outside the governance map",
            "needs_judgment": f"Should `{rel_path}` be governed? If yes, declare it as a copy of the right root (e.g. install docs → init_context_gc.py; README variants → SKILL.md). If it genuinely needs no governance, leave it — this is a prompt, not a verdict.",
        })
    return findings


def _governable_toplevel_files(target: pathlib.Path) -> list[str]:
    """Relative paths of existing files that match the governable-toplevel pattern."""
    out = []
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(target).as_posix()
        if rel.count("/") > 1:
            continue  # top level or one dir deep (scripts/install.sh) only
        if GOVERNABLE_TOPLEVEL.match(rel):
            out.append(rel)
    return out


def _sources_domains(target: pathlib.Path):
    """Parse SOURCES.md into domains (reuses minor_gc), or [] if absent/unparseable."""
    src = target / "SOURCES.md"
    if not src.exists():
        return []
    try:
        import minor_gc
        return minor_gc.parse_sources(src)
    except Exception:
        return []


def _domain_last_verified(target: pathlib.Path) -> dict[str, str]:
    """Map domain name → its 'Last verified: YYYY-MM-DD' string (parse_sources drops this field)."""
    src = target / "SOURCES.md"
    out: dict[str, str] = {}
    if not src.exists():
        return out
    cur = None
    for line in src.read_text(encoding="utf-8").splitlines():
        m = re.match(r"###\s+`?([^`—#]+)`?", line)
        if m:
            cur = m.group(1).strip()
            continue
        if cur:
            mv = re.search(r"\*\*Last verified:\*\*\s*`?(\d{4}-\d{2}-\d{2})`?", line)
            if mv:
                out[cur] = mv.group(1)
    return out


def check_stale_verification(target: pathlib.Path, max_age_days: int = 120) -> list[dict]:
    """TTL drift — a SOURCES domain whose `Last verified` is older than max_age_days needs re-check.

    The authority map records when each domain was last confirmed against its root. That timestamp is
    itself a perishable claim: a domain verified months ago may have silently drifted since. This
    surfaces domains overdue for re-verification — a prompt to re-run the domain's Re-check, not a
    verdict that it drifted.
    """
    now = int(time.time())
    findings = []
    for name, datestr in _domain_last_verified(target).items():
        try:
            y, mo, d = (int(x) for x in datestr.split("-"))
            epoch = int(time.mktime((y, mo, d, 0, 0, 0, 0, 0, -1)))
        except Exception:
            continue
        age = (now - epoch) / 86400
        if age > max_age_days:
            findings.append({
                "type": "stale-verification",
                "status": "NEEDS_JUDGMENT",
                "severity": "low",
                "file": "SOURCES.md",
                "detail": f"domain `{name}` last verified {datestr} (~{int(age)} days ago) — overdue for re-check",
                "needs_judgment": f"Re-run `{name}`'s Re-check command and confirm it still holds, then bump Last verified. The timestamp is a claim that perishes; old ≠ drifted, but it earns a re-look.",
            })
    return findings


def check_orphaned_roots(target: pathlib.Path) -> list[dict]:
    """Deletion drift — a SOURCES domain whose root file no longer exists on disk.

    The reverse of orphan-reference (which catches a reference to a missing file). Here the *root* —
    the authority a domain is built on — was deleted, leaving the domain (and its copies) governing
    nothing. The copies become unanchored: still declared, but their truth source is gone.
    """
    findings = []
    for d in _sources_domains(target):
        root = (d.root or "").strip().rstrip("/")
        if not root or d.status in {"HISTORICAL"}:
            continue
        # External roots (URLs, or paths with no suffix that look like services) are out of scope here.
        if URL_RE.search(root) or "://" in root:
            continue
        rp = target / root
        if not rp.exists():
            findings.append({
                "type": "orphaned-root",
                "status": "NEEDS_JUDGMENT",
                "severity": "medium",
                "file": "SOURCES.md",
                "detail": f"domain `{d.name}` root `{root}` no longer exists; its copies now govern nothing",
                "needs_judgment": f"The root `{root}` was deleted. Did a copy become the new root? Should the domain be removed, or marked HISTORICAL? Decide before the orphaned copies drift unwatched.",
            })
    return findings


def check_implementation_gap(target: pathlib.Path) -> list[dict]:
    """Reverse spec-drift — a DOC root is git-newer than the CODE copy that should implement it.

    spec-drift-candidate catches "code moved, doc lags". This is the mirror: a spec/design DOC is the
    declared root and a CODE file is its copy, but the code is git-OLDER than the spec — the spec was
    updated and the code has not caught up yet (an implementation gap). SKILL names this
    `flag_implementation_gap`; this is its mechanical trigger.
    """
    findings = []
    for d in _sources_domains(target):
        root = (d.root or "").strip()
        if not root or pathlib.PurePath(root).suffix.lower() not in {".md", ".mdx"}:
            continue  # only DOC/spec roots
        if d.status in {"FORK", "HISTORICAL", "UNKNOWN_ROOT"}:
            continue
        root_epoch = git_last_commit_epoch(target, root)
        if root_epoch is None:
            continue
        for copy in d.copies:
            copy = copy.strip()
            if pathlib.PurePath(copy).suffix.lower() not in CODE_SUFFIXES:
                continue  # only CODE copies can have an implementation gap
            copy_epoch = git_last_commit_epoch(target, copy)
            if copy_epoch is None or root_epoch <= copy_epoch:
                continue  # code is same-age-or-newer → presumed implemented
            findings.append({
                "type": "implementation-gap",
                "status": "NEEDS_JUDGMENT",
                "severity": "medium",
                "file": copy,
                "detail": f"spec root `{root}` committed after code `{copy}`; the code may not yet implement the updated spec",
                "needs_judgment": f"Read `{root}` and `{copy}`: does the code implement the current spec? If the spec is the intent and code lags, this is an implementation gap to flag, not a doc to rewrite.",
            })
    return findings


ENV_FILE_RE = re.compile(r"(^|/)\.env(\.[\w-]+)?$|(^|/)[\w-]*config[\w.-]*\.(ya?ml|toml|ini|json)$", re.I)


def check_env_matrix_drift(target: pathlib.Path) -> list[dict]:
    """Environment drift — env/config files that exist but aren't declared FORK or governed.

    dev/staging/prod configs (.env.local, config.prod.yaml, ...) are SUPPOSED to diverge — but only
    intentionally (a declared FORK). An env-looking file that is neither governed nor marked FORK is a
    candidate for unintentional drift: is its divergence deliberate, or did it quietly fall out of sync
    with the others? Low severity, narrow to env/config shapes, excludes the demo fixtures.
    """
    declared = set()
    fork_domains = []
    for d in _sources_domains(target):
        if d.root:
            declared.add(d.root.strip().rstrip("/"))
        for c in d.copies:
            declared.add(c.strip())
        if d.status == "FORK":
            fork_domains.append(d.name)
    findings = []
    seen = []
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(target).as_posix()
        if _excluded(rel, DEFAULT_EXCLUDES) or "examples/" in rel or "templates/" in rel:
            continue
        if rel.endswith(".example") or rel.endswith(".sample"):
            continue
        if ENV_FILE_RE.search(rel) and rel not in declared:
            seen.append(rel)
    # Only flag when there's an actual MATRIX: 2+ env/config files sharing a stem (dev/prod siblings).
    by_stem: dict[str, list[str]] = {}
    for rel in seen:
        stem = re.sub(r"\.(local|dev|prod|production|staging|test|example)\b", "", pathlib.PurePath(rel).name, flags=re.I)
        by_stem.setdefault(f"{pathlib.PurePath(rel).parent}/{stem}", []).append(rel)
    for group in by_stem.values():
        if len(group) >= 2:
            findings.append({
                "type": "env-matrix-drift",
                "status": "NEEDS_JUDGMENT",
                "severity": "low",
                "files": sorted(group),
                "detail": f"{len(group)} env/config siblings not declared FORK; their divergence may be unintentional",
                "needs_judgment": "If these intentionally differ per environment, declare the relationship as FORK in SOURCES.md so it stops re-flagging. If they should agree, reconcile to a root.",
            })
    return findings


def check_structural_drift(target: pathlib.Path) -> list[dict]:
    """Structural drift — a code file's PUBLIC INTERFACE gained a handle its doc never mentions.

    Value/link/duplicate checks compare strings; this compares SHAPE. The hard part is "public": a
    naive scan of every `def`'s params floods on internal helpers (cfg, argv, Any, section_name...).
    So this only looks at genuinely public surface a doc is expected to track:
      - argparse CLI flags:  add_argument("--foo")   → docs should mention `--foo`
    A CLI flag the code defines but no doc copy mentions is a real structural gap. Narrow on purpose —
    better to catch only CLI drift reliably than to flood on every internal function parameter.
    """
    findings = []
    for d in _sources_domains(target):
        root = (d.root or "").strip()
        if not root or pathlib.PurePath(root).suffix.lower() not in CODE_SUFFIXES:
            continue
        if d.status in {"FORK", "HISTORICAL", "UNKNOWN_ROOT"}:
            continue
        rp = target / root
        if not rp.exists():
            continue
        code = _read_text(rp)
        # Public surface = CLI flags the tool exposes. These are what user-facing docs must track.
        flags = set(re.findall(r"add_argument\(\s*[\"'](--[a-z][a-z0-9-]+)[\"']", code))
        if not flags:
            continue
        doc_copies = [c.strip() for c in d.copies if pathlib.PurePath(c.strip()).suffix.lower() in {".md", ".mdx"}]
        if not doc_copies:
            continue
        doc_text = ""
        for c in doc_copies:
            cp = target / c
            if cp.exists():
                doc_text += _read_text(cp)
        undocumented = sorted(f for f in flags if f not in doc_text)
        if undocumented and len(undocumented) >= max(2, len(flags) // 2):
            findings.append({
                "type": "structural-drift",
                "status": "NEEDS_JUDGMENT",
                "severity": "low",
                "file": doc_copies[0],
                "detail": f"code root `{root}` exposes CLI flags not mentioned in its docs: {', '.join(undocumented[:6])}",
                "needs_judgment": f"The tool's public CLI grew. Confirm whether `{doc_copies[0]}` should document {', '.join(undocumented[:4])} — structure drift, not value drift.",
            })
    return findings


def check_external_root_drift(target: pathlib.Path) -> list[dict]:
    """External-root drift — a domain whose root is OUTSIDE the repo (a URL/API/upstream) can't be
    checked by local git mtime, so it silently never gets verified.

    SKILL says roots can be external (an API, a server, an upstream lib). But every mechanical check
    here works on local files. An external-root domain is therefore in a permanent blind spot: nothing
    triggers a re-check when the upstream changes. This surfaces those domains so a human/agent probes
    the external root — context-gc stays zero-dependency and does NOT fetch the URL itself.
    """
    findings = []
    for d in _sources_domains(target):
        root = (d.root or "").strip()
        if not root:
            continue
        is_external = bool(URL_RE.search(root) or "://" in root) or (
            "/" not in root and "." not in root and root.lower() not in {"code"} and len(root.split()) > 1
        )
        if not is_external:
            continue
        if d.status in {"HISTORICAL", "FORK"}:
            continue
        findings.append({
            "type": "external-root-drift",
            "status": "NEEDS_JUDGMENT",
            "severity": "medium",
            "file": "SOURCES.md",
            "detail": f"domain `{d.name}` has an external root `{root}` that local checks can never verify",
            "needs_judgment": f"Probe the external root `{root}` (call the API / check the upstream version) and confirm the local copies still match it. context-gc won't fetch it for you — this is the trigger to do it.",
        })
    return findings


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
        + check_orphan_command_refs(target, files)
        + check_duplicates(target, files)
        + check_spec_drift_candidates(target)
        + check_coverage_gaps(target)
        + check_stale_verification(target)
        + check_orphaned_roots(target)
        + check_implementation_gap(target)
        + check_env_matrix_drift(target)
        + check_structural_drift(target)
        + check_external_root_drift(target)
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
        "scope": current_scope(target),
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
