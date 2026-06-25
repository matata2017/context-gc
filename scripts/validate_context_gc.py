#!/usr/bin/env python3
"""Lightweight repository validation for context-gc.

This is not a replacement for human evals. It catches structural regressions:
- SKILL.md frontmatter has name + description
- description is concise enough for trigger metadata
- evals/evals.json follows the skill-creator shape
- hook helper can parse a representative event
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
EVALS = ROOT / "evals" / "evals.json"
HOOK = ROOT / "scripts" / "context_gc_hook.py"
SOURCES = ROOT / "SOURCES.md"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        fail("SKILL.md must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        fail("SKILL.md frontmatter is not closed")
    fm = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm


def main() -> int:
    text = SKILL.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    if fm.get("name") != "context-gc":
        fail("frontmatter name must be context-gc")
    desc = fm.get("description", "")
    if not desc:
        fail("frontmatter description is required")
    if len(desc) > 240:
        fail(f"description too long for trigger metadata: {len(desc)} chars")
    if "Use when" not in desc and "use when" not in desc:
        fail("description should include a trigger cue such as 'Use when'")
    if "resources:" in text[: text.find("\n---\n", 4)]:
        fail("SKILL.md frontmatter should only include Claude skill metadata needed by the package")

    data = json.loads(EVALS.read_text(encoding="utf-8"))
    if data.get("skill_name") != "context-gc":
        fail("evals.json must have skill_name=context-gc")
    evals = data.get("evals")
    if not isinstance(evals, list) or len(evals) < 35:
        fail("evals.json must contain at least 35 evals")
    for e in evals:
        for key in ("id", "name", "prompt", "expected_output", "assertions"):
            if key not in e:
                fail(f"eval missing {key}: {e}")
        if not isinstance(e["assertions"], list) or len(e["assertions"]) < 3:
            fail(f"eval assertions too weak: {e.get('name')}")

    for demo in (
        "demo-doc-vs-config",
        "demo-sdd-drift",
        "demo-agent-context-rot",
        "demo-agent-drift-advanced",
        "demo-minor-gc",
        "demo-memory-drift",
        "demo-review-queue",
        "demo-kb-duplication",
        "demo-agent-autonomy",
        "demo-hill-climb",
    ):
        path = ROOT / "examples" / demo
        if not path.exists():
            fail(f"missing demo: {demo}")
        if demo == "demo-minor-gc":
            if not (path / "expected-minor-gc-report.md").exists():
                fail(f"demo missing expected minor GC report: {demo}")
        elif demo == "demo-memory-drift":
            if not (path / "expected-memory-gc-report.md").exists():
                fail(f"demo missing expected memory GC report: {demo}")
        elif demo == "demo-review-queue":
            if not (path / "expected-review-queue.md").exists():
                fail(f"demo missing expected review queue: {demo}")
        elif demo == "demo-agent-autonomy":
            if not (path / "expected-tick.md").exists():
                fail(f"demo missing expected tick: {demo}")
        elif demo == "demo-hill-climb":
            if not (path / "expected-hill-climb.md").exists():
                fail(f"demo missing expected hill-climb: {demo}")
        elif not (path / "expected-entropy-report.md").exists():
            fail(f"demo missing expected report: {demo}")

    if not SOURCES.exists():
        fail("missing SOURCES.md write barrier")
    sources = SOURCES.read_text(encoding="utf-8")
    for domain in ("skill-protocol", "hook-behavior", "eval-fixtures", "runner-scripts"):
        if domain not in sources:
            fail(f"SOURCES.md missing domain: {domain}")

    for script in ("init_context_gc.py", "mark.py", "minor_gc.py", "session_mark.py", "review_queue.py", "resolve.py", "gc_tick.py", "analyze_patterns.py", "_common.py"):
        if not (ROOT / "scripts" / script).exists():
            fail(f"missing runner script: scripts/{script}")

    # Dogfood self-check: context-gc's own write barrier must not drift from reality. Every demo
    # directory must be cited in SOURCES.md, and every runner script must be referenced in README.md.
    # This makes the exact drift we caused during development a red CI gate next time.
    demo_dirs = sorted(p.name for p in (ROOT / "examples").glob("demo-*") if p.is_dir())
    for demo in demo_dirs:
        if demo not in sources:
            fail(f"SOURCES.md (eval-fixtures) is stale: demo `{demo}` exists but is not cited")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for script_path in sorted((ROOT / "scripts").glob("*.py")):
        name = script_path.name
        if name in {"_common.py", "run_evals.py", "validate_context_gc.py"}:
            continue  # internal/test scaffolding, not user-facing runners
        if name not in readme:
            fail(f"README.md Files tree is stale: runner `scripts/{name}` is not listed")

    proc = subprocess.run(
        [sys.executable, str(HOOK), "dirty-card"],
        input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": "docs/test.md"}}),
        text=True,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        fail(f"hook dirty-card failed: {proc.stderr}")
    subprocess.run([sys.executable, str(HOOK), "clear"], cwd=ROOT, check=False)

    guard = subprocess.run(
        [sys.executable, str(HOOK), "sweep-guard"],
        input=json.dumps({"tool_name": "MultiEdit", "tool_input": {"file_path": "SKILL.md", "edits": []}}),
        text=True,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if guard.returncode != 0:
        fail(f"hook sweep-guard failed: {guard.stderr}")
    if "permissionDecision" not in guard.stdout or "deny" not in guard.stdout:
        fail("hook sweep-guard should deny unapproved high-risk context edits")

    self_test = subprocess.run(
        [sys.executable, str(HOOK), "--self-test"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if self_test.returncode != 0:
        fail(f"hook self-test failed: {self_test.stderr}")

    print("OK: context-gc structure validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
