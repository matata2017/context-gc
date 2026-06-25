#!/usr/bin/env python3
"""Preventive minor GC for context-bearing files.

Minor GC is a small-scope guard for automated agent tasks: it reads dirty cards and SOURCES.md
contracts, reports touched domains, and optionally applies only pre-authorized safe fixers. It never
chooses authority and never edits protected files.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import pathlib
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

DEFAULT_PROTECTED = ["CLAUDE.md", "SOUL.md", "memory/**", "skills/**/SKILL.md", "docs/adr/**", "docs/sdd/**"]
DEFAULT_FIXERS = ["scalar-sync", "pointer-copy", "generated-state-cleanup"]
SKIP_STATUSES = {"UNKNOWN_ROOT", "FORK", "HISTORICAL"}


@dataclass
class Domain:
    name: str
    root: str = ""
    copies: list[str] = field(default_factory=list)
    status: str = "NOT_CHECKED"
    autofix: str = ""
    root_extract: str = ""
    copy_replace: str = ""
    pointer_text: str = ""
    memory_subject: str = ""
    memory_target: str = ""
    archive_path: str = ""
    protected: bool = False


def load_config(target: pathlib.Path) -> dict[str, Any]:
    cfg = {
        "enabled": False,
        "interval_dirty_cards": 10,
        "interval_turns": 10,
        "apply_safe": False,
        "max_files_per_run": 3,
        "max_seconds": 5,
        "allow_fixers": DEFAULT_FIXERS[:],
        "protected": DEFAULT_PROTECTED[:],
        "memory_gc_enabled": False,
        "memory_gc_allow_archive": False,
        "memory_gc_max_files_per_run": 5,
        "memory_gc_protected_subjects": ["identity", "credentials", "legal"],
    }
    path = target / ".context-gc" / "config.yml"
    if not path.exists():
        return cfg
    lines = path.read_text(encoding="utf-8").splitlines()
    section = None
    list_key = None
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("minor_gc:"):
            section = "minor_gc"
            list_key = None
            continue
        if stripped.startswith("memory_gc:"):
            section = "memory_gc"
            list_key = None
            continue
        if section not in {"minor_gc", "memory_gc"}:
            continue
        if raw and not raw.startswith(" "):
            section = None
            list_key = None
            continue
        if ":" not in stripped and not stripped.startswith("- "):
            continue
        if stripped.startswith("- ") and list_key:
            cfg.setdefault(list_key, []).append(stripped[2:].strip().strip('"'))
            continue
        if ":" not in stripped:
            continue
        key, val = stripped.split(":", 1)
        key = key.strip()
        val = val.strip().split("#", 1)[0].strip().strip('"')
        list_key = None
        if section == "minor_gc":
            if key in {"allow_fixers", "protected"}:
                cfg[key] = []
                list_key = key
            elif key in {"enabled", "apply_safe", "require_clean_git"}:
                cfg[key] = val.lower() == "true"
            elif key in {"interval_dirty_cards", "interval_turns", "max_files_per_run", "max_seconds"}:
                try:
                    cfg[key] = int(val)
                except ValueError:
                    pass
            elif val:
                cfg[key] = val
        elif section == "memory_gc":
            if key == "protected_subjects":
                cfg["memory_gc_protected_subjects"] = []
                list_key = "memory_gc_protected_subjects"
            elif key == "enabled":
                cfg["memory_gc_enabled"] = val.lower() == "true"
            elif key == "allow_archive":
                cfg["memory_gc_allow_archive"] = val.lower() == "true"
            elif key == "max_files_per_run":
                try:
                    cfg["memory_gc_max_files_per_run"] = int(val)
                except ValueError:
                    pass
            elif key == "mode" and val:
                cfg["memory_gc_mode"] = val
    return cfg


def clean_path(raw: str) -> str:
    text = raw.strip()
    m = re.search(r"`([^`]+)`", text)
    if m:
        return m.group(1).replace("\\", "/")
    value = text.split(" ", 1)[0].strip("`")
    return value.replace("\\", "/")


def parse_sources(path: pathlib.Path) -> list[Domain]:
    if not path.exists():
        return []
    domains: list[Domain] = []
    cur: Domain | None = None
    in_copies = False
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"###\s+`?([^`—#]+)`?", line)
        if m:
            if cur:
                domains.append(cur)
            cur = Domain(name=m.group(1).strip())
            in_copies = False
            continue
        if not cur:
            continue
        stripped = line.strip()
        if stripped.startswith("- **Root:**"):
            cur.root = clean_path(stripped.split(":**", 1)[1])
            in_copies = False
        elif stripped.startswith("- **Copies:**"):
            in_copies = True
        elif in_copies and stripped.startswith("- `"):
            cur.copies.append(clean_path(stripped[2:]))
        elif stripped.startswith("- **Auto-fix:**"):
            cur.autofix = stripped.split(":**", 1)[1].strip().strip("`")
            in_copies = False
        elif stripped.startswith("- **Root extract:**"):
            cur.root_extract = stripped.split(":**", 1)[1].strip().strip("`")
            in_copies = False
        elif stripped.startswith("- **Copy replace:**"):
            cur.copy_replace = stripped.split(":**", 1)[1].strip().strip("`")
            in_copies = False
        elif stripped.startswith("- **Pointer text:**"):
            cur.pointer_text = stripped.split(":**", 1)[1].strip().strip("`")
            in_copies = False
        elif stripped.startswith("- **Memory subject:**"):
            cur.memory_subject = stripped.split(":**", 1)[1].strip().strip("`")
            in_copies = False
        elif stripped.startswith("- **Memory target:**"):
            cur.memory_target = clean_path(stripped.split(":**", 1)[1])
            in_copies = False
        elif stripped.startswith("- **Archive path:**"):
            cur.archive_path = clean_path(stripped.split(":**", 1)[1])
            in_copies = False
        elif stripped.startswith("- **Protected:**"):
            cur.protected = "true" in stripped.lower()
            in_copies = False
        elif stripped.startswith("- **Status:**"):
            m_status = re.search(r"`?([A-Z_]+)`?", stripped.split(":**", 1)[1])
            cur.status = m_status.group(1) if m_status else cur.status
            in_copies = False
    if cur:
        domains.append(cur)
    return domains


def dirty_paths(target: pathlib.Path) -> set[str]:
    path = target / ".context-gc" / "dirty.jsonl"
    if not path.exists():
        return set()
    paths = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        p = item.get("path")
        if p:
            paths.add(str(p).replace("\\", "/"))
    return paths


def is_protected(rel: str, protected: list[str]) -> bool:
    rel = rel.replace("\\", "/")
    name = pathlib.PurePath(rel).name
    return any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat) for pat in protected)


def touched(domain: Domain, dirty: set[str]) -> bool:
    if not dirty:
        return True
    paths = {domain.root, *domain.copies}
    return any(p in dirty for p in paths if p)


def result(status: str, domain: Domain, detail: str, path: str = "", old: str = "", new: str = "") -> dict[str, Any]:
    return {"status": status, "domain": domain.name, "path": path, "detail": detail, "old": old, "new": new}


def scalar_sync(target: pathlib.Path, domain: Domain, apply: bool, protected: list[str]) -> list[dict[str, Any]]:
    out = []
    root_path = target / domain.root
    if not root_path.exists() or not domain.root_extract or not domain.copy_replace:
        return [result("NEEDS_REVIEW", domain, "scalar-sync requires existing root, Root extract, and Copy replace")]
    root_text = root_path.read_text(encoding="utf-8")
    matches = re.findall(domain.root_extract, root_text, re.MULTILINE)
    if len(matches) != 1:
        return [result("NEEDS_REVIEW", domain, f"Root extract matched {len(matches)} time(s)")]
    value = matches[0][0] if isinstance(matches[0], tuple) else matches[0]
    for copy in domain.copies:
        if is_protected(copy, protected):
            out.append(result("PROTECTED_SKIP", domain, "copy path is protected", copy))
            continue
        copy_path = target / copy
        if not copy_path.exists():
            out.append(result("NEEDS_REVIEW", domain, "copy path missing", copy))
            continue
        text = copy_path.read_text(encoding="utf-8")
        found = re.findall(domain.copy_replace, text, re.MULTILINE)
        if len(found) != 1:
            out.append(result("NEEDS_REVIEW", domain, f"Copy replace matched {len(found)} time(s)", copy))
            continue
        old = found[0][0] if isinstance(found[0], tuple) else found[0]
        def repl(match: re.Match) -> str:
            if match.lastindex:
                return match.group(0).replace(match.group(1), str(value), 1)
            return str(value)
        new_text = re.sub(domain.copy_replace, repl, text, count=1, flags=re.MULTILINE)
        if new_text == text:
            out.append(result("REPORT_ONLY", domain, "copy already appears synced or replacement produced no change", copy, str(old), str(value)))
            continue
        if apply:
            copy_path.write_text(new_text, encoding="utf-8")
            out.append(result("AUTO_FIXED", domain, "scalar synced from root", copy, str(old), str(value)))
        else:
            out.append(result("REPORT_ONLY", domain, "would scalar sync from root", copy, str(old), str(value)))
    return out


def pointer_copy(target: pathlib.Path, domain: Domain, apply: bool, protected: list[str]) -> list[dict[str, Any]]:
    out = []
    if not domain.pointer_text:
        return [result("NEEDS_REVIEW", domain, "pointer-copy requires Pointer text")]
    for copy in domain.copies:
        if is_protected(copy, protected):
            out.append(result("PROTECTED_SKIP", domain, "copy path is protected", copy))
            continue
        copy_path = target / copy
        if not copy_path.exists():
            out.append(result("NEEDS_REVIEW", domain, "copy path missing", copy))
            continue
        text = copy_path.read_text(encoding="utf-8")
        if domain.pointer_text in text:
            out.append(result("REPORT_ONLY", domain, "pointer already present", copy))
            continue
        if apply:
            copy_path.write_text(domain.pointer_text.rstrip() + "\n", encoding="utf-8")
            out.append(result("AUTO_FIXED", domain, "replaced copy with declared pointer", copy))
        else:
            out.append(result("REPORT_ONLY", domain, "would replace copy with declared pointer", copy))
    return out


def generated_state_cleanup(target: pathlib.Path, domain: Domain, apply: bool) -> list[dict[str, Any]]:
    dirty = target / ".context-gc" / "dirty.jsonl"
    if apply and dirty.exists():
        lines = [ln for ln in dirty.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if len(lines) > 200:
            dirty.write_text("\n".join(lines[-200:]) + "\n", encoding="utf-8")
            return [result("AUTO_FIXED", domain, "rotated dirty cards to the latest 200 entries", ".context-gc/dirty.jsonl")]
    return [result("REPORT_ONLY", domain, "generated state cleanup checked", ".context-gc/")]


def memory_condense(target: pathlib.Path, domain: Domain, apply: bool, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    if not cfg.get("memory_gc_enabled"):
        return [result("REPORT_ONLY", domain, "memory_gc is disabled; would write memory condensation report")]
    subject = domain.memory_subject or domain.name
    protected_subjects = cfg.get("memory_gc_protected_subjects", [])
    if any(p in subject for p in protected_subjects):
        return [result("PROTECTED_SKIP", domain, f"memory subject `{subject}` is protected")]
    target_rel = domain.memory_target or domain.root
    if not target_rel:
        return [result("NEEDS_REVIEW", domain, "memory-condense requires Memory target or Root")]
    sources = []
    for rel in [domain.root, *domain.copies]:
        if not rel:
            continue
        path = target / rel
        if path.exists() and path.is_file():
            sources.append((rel, path.read_text(encoding="utf-8")))
    if len(sources) < 2:
        return [result("NEEDS_REVIEW", domain, "memory-condense needs at least two source memories")]
    joined = "\n".join(text.lower() for _, text in sources)
    conflict_pairs = [("concise", "verbose"), ("concise", "detailed"), ("brief", "step-by-step"), ("direct", "warm")]
    conflicts = [f"{a} vs {b}" for a, b in conflict_pairs if a in joined and b in joined]
    if conflicts:
        _write_memory_report(target, [{"status": "CONFLICT_NEEDS_REVIEW", "domain": domain.name, "detail": ", ".join(conflicts), "sources": [rel for rel, _ in sources]}])
        return [result("NEEDS_REVIEW", domain, "memory conflict needs review: " + ", ".join(conflicts))]
    # The contract author declares Root as the authoritative/latest memory; condense uses it as the
    # canonical content and keeps every source as evidence.
    latest_rel, latest_text = sources[0]
    summary = _memory_summary(subject, latest_rel, latest_text, sources)
    out = []
    target_path = target / target_rel
    if apply:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(summary, encoding="utf-8")
        out.append(result("AUTO_FIXED", domain, "CURRENT_MEMORY_WRITTEN", target_rel))
        if cfg.get("memory_gc_allow_archive") and domain.archive_path:
            archive_dir = target / domain.archive_path
            archive_dir.mkdir(parents=True, exist_ok=True)
            for rel, text in sources:
                if rel == target_rel:
                    continue
                src = target / rel
                if src.exists() and src.is_file():
                    dst = archive_dir / pathlib.PurePath(rel).name
                    src.replace(dst)
                    out.append(result("AUTO_FIXED", domain, "ARCHIVED", dst.relative_to(target).as_posix()))
    else:
        out.append(result("REPORT_ONLY", domain, "would write current memory summary", target_rel))
    _write_memory_report(target, [{"status": "CURRENT_MEMORY_WRITTEN" if apply else "REPORT_ONLY", "domain": domain.name, "path": target_rel, "sources": [rel for rel, _ in sources]}])
    return out


def _memory_summary(subject: str, latest_rel: str, latest_text: str, sources: list[tuple[str, str]]) -> str:
    clean = latest_text.strip()
    if clean.startswith("---\n"):
        end = clean.find("\n---\n", 4)
        if end != -1:
            clean = clean[end + 5 :].strip()
    evidence = "\n".join(f"  - `{rel}`" for rel, _ in sources)
    return (
        "---\n"
        f"memory_type: long-term\nsubject: {subject}\nstatus: current\n---\n\n"
        f"# Current memory — {subject}\n\n"
        f"{clean}\n\n"
        "## Evidence\n"
        f"{evidence}\n"
    )


def _write_memory_report(target: pathlib.Path, entries: list[dict[str, Any]]) -> None:
    state_dir = target / ".context-gc"
    state_dir.mkdir(exist_ok=True)
    payload = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "entries": entries}
    (state_dir / "memory-gc.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Memory GC report", ""]
    for entry in entries:
        lines.append(f"## {entry.get('status')}")
        lines.append("")
        lines.append(f"- `{entry.get('domain')}` {entry.get('path', '')}: {entry.get('detail', '')}")
        if entry.get("sources"):
            lines.append("- Evidence:")
            for src in entry["sources"]:
                lines.append(f"  - `{src}`")
        lines.append("")
    (state_dir / "memory-gc-report.md").write_text("\n".join(lines), encoding="utf-8")


def process_domain(target: pathlib.Path, domain: Domain, cfg: dict[str, Any], apply: bool) -> list[dict[str, Any]]:
    protected = cfg.get("protected", DEFAULT_PROTECTED)
    if domain.status in SKIP_STATUSES:
        return [result(f"{domain.status}_SKIP", domain, f"domain status is {domain.status}; report-only")]
    # memory-condense reads protected memory files on purpose, so it runs before the protected-path guard.
    if domain.autofix == "memory-condense":
        if "memory-condense" not in cfg.get("allow_fixers", DEFAULT_FIXERS):
            return [result("NEEDS_REVIEW", domain, "fixer `memory-condense` is not allowed by config")]
        return memory_condense(target, domain, apply, cfg)
    if domain.protected or any(is_protected(p, protected) for p in [domain.root, *domain.copies] if p):
        return [result("PROTECTED_SKIP", domain, "domain touches protected path")]
    if not domain.autofix:
        return [result("REPORT_ONLY", domain, "no Auto-fix contract declared")]
    if domain.autofix not in cfg.get("allow_fixers", DEFAULT_FIXERS):
        return [result("NEEDS_REVIEW", domain, f"fixer `{domain.autofix}` is not allowed by config")]
    if domain.autofix == "scalar-sync":
        return scalar_sync(target, domain, apply, protected)
    if domain.autofix == "pointer-copy":
        return pointer_copy(target, domain, apply, protected)
    if domain.autofix == "generated-state-cleanup":
        return generated_state_cleanup(target, domain, apply)
    return [result("NEEDS_REVIEW", domain, f"unknown fixer `{domain.autofix}`")]


def render_report(target_name: str, results: list[dict[str, Any]], apply: bool) -> str:
    lines = [
        f"# Minor GC report — {target_name}",
        "",
        f"Mode: {'apply-safe' if apply else 'report-only'}",
        "",
    ]
    if not results:
        lines.append("No dirty SOURCES.md domains matched. Nothing to do.")
        return "\n".join(lines) + "\n"
    for status in ("AUTO_FIXED", "CURRENT_MEMORY_WRITTEN", "ARCHIVED", "REPORT_ONLY", "PROTECTED_SKIP", "UNKNOWN_ROOT_SKIP", "FORK_SKIP", "HISTORICAL_SKIP", "CONFLICT_NEEDS_REVIEW", "NEEDS_REVIEW"):
        group = [r for r in results if r["status"] == status]
        if not group:
            continue
        lines.append(f"## {status}")
        lines.append("")
        for r in group:
            path = f" `{r['path']}`" if r.get("path") else ""
            change = f" ({r['old']} → {r['new']})" if r.get("old") or r.get("new") else ""
            lines.append(f"- `{r['domain']}`{path}: {r['detail']}{change}")
        lines.append("")
    lines.append("Minor GC only applies pre-authorized safe fixers. Protected, historical, forked, and unknown-root domains require review.")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Preventive minor GC for dirty context domains")
    ap.add_argument("--target", default=".")
    ap.add_argument("--apply-safe", action="store_true")
    ap.add_argument("--max-files", type=int, default=None)
    ap.add_argument("--max-seconds", type=int, default=None)
    args = ap.parse_args()

    target = pathlib.Path(args.target).resolve()
    if not target.is_dir():
        print(f"FAIL: target is not a directory: {target}")
        return 1
    start = time.time()
    cfg = load_config(target)
    apply = bool(args.apply_safe) if args.apply_safe else bool(cfg.get("apply_safe"))
    max_files = args.max_files or int(cfg.get("max_files_per_run", 3))
    max_seconds = args.max_seconds or int(cfg.get("max_seconds", 5))
    dirty = dirty_paths(target)
    domains = [d for d in parse_sources(target / "SOURCES.md") if touched(d, dirty)]
    domains = domains[:max_files]
    results: list[dict[str, Any]] = []
    for domain in domains:
        if time.time() - start > max_seconds:
            results.append(result("NEEDS_REVIEW", domain, "minor GC time budget exhausted"))
            break
        results.extend(process_domain(target, domain, cfg, apply))

    state_dir = target / ".context-gc"
    state_dir.mkdir(exist_ok=True)
    payload = {
        "target": target.name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "apply_safe": apply,
        "dirty_paths": sorted(dirty),
        "results": results,
    }
    (state_dir / "minor-gc.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render_report(target.name, results, apply)
    (state_dir / "minor-gc-report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
