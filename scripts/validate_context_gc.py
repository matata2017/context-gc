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

    data = json.loads(EVALS.read_text(encoding="utf-8"))
    if data.get("skill_name") != "context-gc":
        fail("evals.json must have skill_name=context-gc")
    evals = data.get("evals")
    if not isinstance(evals, list) or len(evals) < 4:
        fail("evals.json must contain at least 4 evals")
    for e in evals:
        for key in ("id", "name", "prompt", "expected_output", "assertions"):
            if key not in e:
                fail(f"eval missing {key}: {e}")
        if not isinstance(e["assertions"], list) or len(e["assertions"]) < 3:
            fail(f"eval assertions too weak: {e.get('name')}")

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

    print("OK: context-gc structure validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
