#!/usr/bin/env python3
"""Shared helpers for context-gc runners.

These keep the mechanical half of MARK deterministic and target-repo aware. Every runner accepts a
target directory so the skill can be installed once and pointed at any repository.
"""
from __future__ import annotations

import fnmatch
import json
import pathlib
import re
import subprocess
import time
from typing import Iterable

# Files that carry "facts" and therefore rot. Mirrors scripts/context_gc_hook.py on purpose; if you
# change one, update the other (they are a declared root/copy pair in SOURCES.md).
CONTEXT_NAMES = {"README", "README.md", "CHANGELOG", "CHANGELOG.md", "CLAUDE.md", "SOUL.md", "SKILL.md"}
CONTEXT_SUFFIXES = {".md", ".mdx", ".yaml", ".yml", ".json", ".toml", ".ini"}
CONTEXT_PARTS = {"docs", "documentation", "wiki", "memory", "skills", ".claude"}
CONFIG_NAMES = {"docker-compose.yml", "docker-compose.yaml", ".env.example"}
AGENT_CONTEXT_NAMES = {"CLAUDE.md", "SOUL.md"}
AGENT_CONTEXT_PARTS = {".claude", "memory", "skills"}

DEFAULT_EXCLUDES = [
    ".git/*",
    "node_modules/*",
    ".venv/*",
    "venv/*",
    "__pycache__/*",
    "*.pyc",
    ".context-gc/*",
    "dist/*",
    "build/*",
    "outputs/*",
    "*/outputs/*",
    "*/.git/*",
    "*/node_modules/*",
    "*/.venv/*",
    "*/__pycache__/*",
]

# Directory names that are NEVER project context — dependency caches, build output, vendored deps,
# tool state. If ANY path segment is one of these, the file is excluded at any depth. This is more
# robust than per-pattern globs: a real Hermes run surfaced 3202 files / 342 noise candidates because
# .bun's deep cache (.bun/install/cache/.../CHANGELOG.md) slipped past node_modules-only excludes.
EXCLUDED_DIR_NAMES = {
    ".git", ".hg", ".svn",
    "node_modules", ".pnpm", ".yarn", "bower_components", "vendor",
    ".venv", "venv", "env", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".bun", ".npm", ".cache", ".cargo", ".gradle", ".m2", ".nuget", ".cocoapods", "Pods",
    "dist", "build", "out", "target", ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache",
    ".context-gc", "outputs", ".terraform", ".serverless", "coverage", ".idea", ".vscode",
}


def is_context_path(rel: str) -> bool:
    p = pathlib.PurePath(rel.replace("\\", "/"))
    name = p.name
    parts = set(p.parts)
    if name in CONTEXT_NAMES or name in CONFIG_NAMES:
        return True
    if p.suffix.lower() in CONTEXT_SUFFIXES and (parts & CONTEXT_PARTS):
        return True
    if p.suffix.lower() == ".md":
        return True
    return False


def is_agent_context_path(rel: str) -> bool:
    p = pathlib.PurePath(rel.replace("\\", "/"))
    name = p.name
    parts = set(p.parts)
    if name in AGENT_CONTEXT_NAMES:
        return True
    if "skills" in parts and name == "SKILL.md":
        return True
    if parts & AGENT_CONTEXT_PARTS:
        return p.suffix.lower() in CONTEXT_SUFFIXES or name == "SKILL.md"
    return False


def iter_context_files(target: pathlib.Path, excludes: list[str] | None = None) -> Iterable[pathlib.Path]:
    excludes = excludes if excludes is not None else DEFAULT_EXCLUDES
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(target).as_posix()
        if _excluded(rel, excludes):
            continue
        if is_context_path(rel):
            yield path


def iter_agent_context_files(target: pathlib.Path, excludes: list[str] | None = None) -> Iterable[pathlib.Path]:
    excludes = excludes if excludes is not None else DEFAULT_EXCLUDES
    for path in iter_context_files(target, excludes):
        rel = path.relative_to(target).as_posix()
        if is_agent_context_path(rel):
            yield path


DATE_STEM_RE = re.compile(r"[-_]?20\d{2}[-_]?(?:0\d|1[0-2])[-_]?(?:[0-3]\d)?")


def is_memory_path(rel: str) -> bool:
    p = pathlib.PurePath(rel.replace("\\", "/"))
    return "memory" in p.parts and p.suffix.lower() in CONTEXT_SUFFIXES


def iter_memory_files(target: pathlib.Path, excludes: list[str] | None = None) -> Iterable[pathlib.Path]:
    excludes = excludes if excludes is not None else DEFAULT_EXCLUDES
    for path in iter_context_files(target, excludes):
        rel = path.relative_to(target).as_posix()
        if is_memory_path(rel):
            yield path


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"')
    return meta, text[end + 5 :]


def memory_subject(path: pathlib.Path, text: str) -> str:
    meta, body = parse_frontmatter(text)
    if meta.get("subject"):
        return meta["subject"]
    stem = DATE_STEM_RE.sub("", path.stem).strip("-_")
    if stem:
        return stem.lower()
    for line in body.splitlines():
        s = line.strip(" #\t")
        if s:
            return re.sub(r"\s+", "-", s.lower())[:80]
    return path.stem.lower()


def memory_type(path: pathlib.Path, text: str) -> str:
    meta, _ = parse_frontmatter(text)
    if meta.get("memory_type"):
        return meta["memory_type"]
    parts = {p.lower() for p in pathlib.PurePath(path.as_posix()).parts}
    if "profile" in parts or "profile" in path.stem.lower():
        return "profile"
    if "mid-term" in parts or "midterm" in parts or "session" in parts:
        return "mid-term"
    if "archive" in parts or "historical" in parts:
        return "historical"
    if meta.get("status") == "superseded":
        return "superseded"
    return "long-term"


def memory_status(text: str) -> str:
    meta, _ = parse_frontmatter(text)
    return meta.get("status", "unknown")


def skill_names(target: pathlib.Path) -> set[str]:
    skills_dir = target / "skills"
    if not skills_dir.exists():
        return set()
    names = set()
    for skill in skills_dir.glob("*/SKILL.md"):
        names.add(skill.parent.name)
    return names


def rough_token_count(text: str) -> int:
    # Dependency-free estimate: English averages ~4 chars/token; CJK is closer to 1 char/token.
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    non_cjk = max(0, len(text) - cjk)
    return max(1, cjk + non_cjk // 4) if text else 0


def _excluded(rel: str, excludes: list[str]) -> bool:
    rel = rel.replace("\\", "/")
    # Fast path: any path segment that is a known dependency/cache/build dir → excluded at any depth.
    if EXCLUDED_DIR_NAMES.intersection(rel.split("/")):
        return True
    return any(fnmatch.fnmatch(rel, pat) for pat in excludes)


def git_last_commit_epoch(target: pathlib.Path, rel: str) -> int | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(target), "log", "-1", "--format=%ct", "--", rel],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        val = out.stdout.strip()
        return int(val) if val else None
    except Exception:
        return None


# --- State scope (branch / commit awareness) -------------------------------------------------
# `.context-gc/` runtime state (dirty cards, patterns, decisions) is global on disk, but the facts
# it records belong to a specific git branch + commit. When the branch changes, the working-tree
# ground truth changes wholesale — old dirty cards point at files that may now be entirely different.
# So context-gc records the scope it last ran under and detects when HEAD has moved out from under it.
# This is the local-file analog of a LangGraph thread_id: state is meaningful only within its scope.

def _git(target: pathlib.Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(target), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        val = out.stdout.strip()
        return val or None
    except Exception:
        return None


def is_git_repo(target: pathlib.Path) -> bool:
    """True only inside a git work tree. No git, no branches → scope logic must not run at all."""
    return _git(target, "rev-parse", "--is-inside-work-tree") == "true"


def current_scope(target: pathlib.Path) -> dict:
    """The git scope the working tree is in right now: branch + HEAD sha. None values if not a repo."""
    return {
        "branch": _git(target, "rev-parse", "--abbrev-ref", "HEAD"),
        "head_sha": _git(target, "rev-parse", "HEAD"),
    }


def recorded_scope(target: pathlib.Path) -> dict | None:
    """The scope context-gc last recorded for this target, or None if never recorded."""
    path = target / ".context-gc" / "scope.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_scope(target: pathlib.Path, scope: dict | None = None) -> dict | None:
    """Record the current (or given) scope to .context-gc/scope.json. Returns what was written.

    No-op (returns None) outside a git repo — there is no branch to scope against, so writing a
    scope file would only add a meaningless all-None record.
    """
    if not is_git_repo(target):
        return None
    scope = scope if scope is not None else current_scope(target)
    state = target / ".context-gc"
    state.mkdir(exist_ok=True)
    payload = {**scope, "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (state / "scope.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def scope_changed(target: pathlib.Path) -> tuple[bool, dict | None, dict]:
    """Has the git branch moved since context-gc last recorded scope?

    Returns (changed, old_scope, new_scope). `changed` is True only when both scopes have a branch
    and they differ — a fresh repo with no recorded scope, or a non-git target, is not a "change".
    Branch is the unit (not sha): a new commit on the same branch is normal incremental work, but a
    branch switch swaps the whole working-tree ground truth and invalidates old dirty cards.
    """
    if not is_git_repo(target):
        return (False, None, {"branch": None, "head_sha": None})
    new = current_scope(target)
    old = recorded_scope(target)
    if old is None or not new.get("branch") or not old.get("branch"):
        return (False, old, new)
    return (old["branch"] != new["branch"], old, new)


# --- Agent autonomy policy -------------------------------------------------------------------
# context-gc is agent-first: a loop/agent drives it and self-resolves the drift it is *allowed* to.
# The human owns the boundary (config) and audits the trail; the agent acts within it. This is the
# direct answer to the principal-agent problem — the agent can loosen `level`, but the NEVER_AUTO
# floor below is enforced in code and cannot be bypassed by config.
#
# NEVER_AUTO is a hard floor: even level=full will not let an agent auto-resolve these classes.
NEVER_AUTO_FLOOR = {"protected", "delete", "memory-condense", "unknown-root"}

# Which finding kinds count as "safe-mechanical" — the only class an agent self-resolves at level=assist.
SAFE_MECHANICAL_KINDS = {"scalar-sync", "pointer-copy", "generated-state-cleanup", "minor-gc-review"}
# Which declarative action ops are mechanical/reversible enough for the agent at assist/auto.
SAFE_MECHANICAL_OPS = {"scalar_sync", "pointer_copy", "generated_state_cleanup", "reconcile_to_root"}

_LEVEL_PRESETS = {
    "off": set(),
    "assist": {"safe-mechanical"},
    "auto": {"safe-mechanical", "consolidate-anchor"},
    "full": {"safe-mechanical", "consolidate-anchor", "sdd-drift", "spec-drift", "contradiction"},
}


def default_autonomy_policy() -> dict:
    return {
        "level": "assist",
        "agent_may_resolve": sorted(_LEVEL_PRESETS["assist"]),
        "min_recommend_confidence": 0.0,
        "never_auto": sorted(NEVER_AUTO_FLOOR),
    }


def load_autonomy_policy(target: pathlib.Path) -> dict:
    """Read the `autonomy:` block from .context-gc/config.yml, falling back to a safe default.

    The returned policy always includes the NEVER_AUTO_FLOOR in `never_auto` regardless of what the
    config says — the floor is non-negotiable.
    """
    policy = default_autonomy_policy()
    cfg = target / ".context-gc" / "config.yml"
    if cfg.exists():
        in_section = False
        list_key = None
        for raw in cfg.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if stripped.startswith("autonomy:"):
                in_section = True
                list_key = None
                continue
            if in_section:
                if stripped and not raw.startswith(" "):
                    break
                if stripped.startswith("- ") and list_key:
                    val = stripped[2:].split("#", 1)[0].strip().strip('"')
                    if val:
                        policy.setdefault(list_key, []).append(val)
                    continue
                if ":" not in stripped:
                    continue
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip().split("#", 1)[0].strip().strip('"')
                list_key = None
                if key in {"agent_may_resolve", "never_auto"}:
                    policy[key] = []
                    list_key = key
                elif key == "level" and val:
                    policy["level"] = val
                elif key == "min_recommend_confidence":
                    try:
                        policy["min_recommend_confidence"] = float(val)
                    except ValueError:
                        pass
    # Apply level preset if agent_may_resolve was not explicitly listed.
    if not policy.get("agent_may_resolve"):
        policy["agent_may_resolve"] = sorted(_LEVEL_PRESETS.get(policy.get("level", "assist"), set()))
    # The floor is always enforced.
    policy["never_auto"] = sorted(set(policy.get("never_auto") or []) | NEVER_AUTO_FLOOR)
    return policy


def agent_may_resolve(item: dict, policy: dict) -> bool:
    """Decide whether an agent may self-resolve a review-queue item under the given policy.

    Hard floor first (never_auto), then confidence, then the allowed-class list. Returns False (=>
    escalate to a human) on any doubt.
    """
    kind = str(item.get("kind", "")).lower()
    policy_class = str(item.get("policy_class", "")).lower()
    recommend = item.get("recommend", -1)
    options = item.get("options", [])

    # NEVER_AUTO floor: ambiguous, protected, delete, or memory-condense always escalate.
    floor = set(policy.get("never_auto") or []) | NEVER_AUTO_FLOOR
    if recommend is None or recommend < 0:
        return False  # unknown-root / genuinely ambiguous
    if policy_class in floor or kind in floor:
        return False
    # The chosen action must not be a delete/memory-condense op.
    try:
        chosen = options[recommend].get("action", {})
    except (IndexError, AttributeError, TypeError):
        return False
    op = str(chosen.get("op", "")).lower()
    if op in {"delete", "set_current_memory", "manual", "defer"}:
        return False  # memory writes + manual/defer are human-reserved
    if recommend < float(policy.get("min_recommend_confidence", 0.0)):
        return False

    allowed = set(policy.get("agent_may_resolve") or [])
    if "safe-mechanical" in allowed and (policy_class == "safe-mechanical" or op in SAFE_MECHANICAL_OPS or kind in SAFE_MECHANICAL_KINDS):
        return True
    # Class-named allowances (e.g. "consolidate-anchor", "sdd-drift") match the item kind.
    if kind in allowed or policy_class in allowed:
        return True
    return False
