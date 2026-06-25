#!/usr/bin/env python3
"""Offline eval fixture checks for context-gc.

These checks do not call an LLM. They make the eval set executable by verifying that every public
demo fixture has enough expected-output evidence to exercise the skill contract.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals" / "evals.json"
EXAMPLES = ROOT / "examples"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def load_text(path: pathlib.Path) -> str:
    if not path.exists():
        fail(f"missing file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def require_terms(label: str, text: str, terms: list[str]) -> None:
    missing = [term for term in terms if term not in text]
    if missing:
        fail(f"{label} missing terms: {', '.join(missing)}")


def require_regex(label: str, text: str, patterns: list[str]) -> None:
    missing = [pattern for pattern in patterns if not re.search(pattern, text, re.MULTILINE)]
    if missing:
        fail(f"{label} missing patterns: {', '.join(missing)}")


def check_evals_json() -> None:
    data = json.loads(load_text(EVALS))
    names = {item["name"] for item in data.get("evals", [])}
    required = {
        "docs-vs-config-port-drift",
        "sdd-drift-after-requirement-change",
        "local-prod-config-version-drift",
        "agent-context-rot-dead-skill",
        "knowledge-base-duplication-compaction",
        "historical-adr-preserve",
        "intentional-config-fork",
        "agent-semantic-instruction-conflict",
        "agent-memory-leak-compaction",
        "agent-skill-bloat-budget",
        "agent-session-context-rot",
        "agent-tone-behavior-drift",
        "minor-gc-safe-port-autofix",
        "minor-gc-protected-agent-conflict",
        "minor-gc-historical-skip",
        "minor-gc-fork-skip",
        "memory-drift-profile-conflict",
        "memory-condense-safe-current-summary",
        "memory-condense-ambiguous-skip",
        "midterm-memory-expired",
        "guided-setup-authorization",
        "review-resolves-memory-conflict",
        "review-preserves-evidence",
        "stop-nudge-when-queue-nonempty",
    }
    missing = sorted(required - names)
    if missing:
        fail(f"evals.json missing required evals: {', '.join(missing)}")
    for item in data["evals"]:
        prompt = item.get("prompt", "")
        expected = item.get("expected_output", "")
        assertions = item.get("assertions", [])
        if "SOURCES.md" not in expected and "SOURCES.md" not in " ".join(assertions):
            fail(f"eval does not exercise write barrier: {item['name']}")
        mark_only = "do not edit" in prompt.lower() or "mark-only" in expected.lower()
        if not mark_only and "confirmation" not in expected.lower() and not any("confirm" in a.lower() or "approval" in a.lower() for a in assertions):
            fail(f"eval does not exercise sweep gate: {item['name']}")
        if not prompt.strip().endswith((".", "?", "!")):
            fail(f"eval prompt should be a complete user request: {item['name']}")


def check_demo_reports() -> None:
    doc_report = load_text(EXAMPLES / "demo-doc-vs-config" / "expected-entropy-report.md")
    require_terms(
        "demo-doc-vs-config report",
        doc_report,
        ["CONTRADICTION", "DRIFTED", "docker-compose.yml", "README.md", "SOURCES.md"],
    )
    require_regex("demo-doc-vs-config report", doc_report, [r"8000", r"8080"])

    agent_report = load_text(EXAMPLES / "demo-agent-context-rot" / "expected-entropy-report.md")
    require_terms(
        "demo-agent-context-rot report",
        agent_report,
        ["ORPHAN", "CONTRADICTION", "DUPLICATE", "old-scraper", "new-scraper", "SOURCES.md"],
    )
    require_regex("demo-agent-context-rot report", agent_report, [r"10 req/s", r"5 req/s"])

    kb_report = load_text(EXAMPLES / "demo-kb-duplication" / "expected-entropy-report.md")
    require_terms(
        "demo-kb-duplication report",
        kb_report,
        ["DUPLICATE", "UNKNOWN_ROOT", "README.md", "docs/deploy.md", "wiki/export.md", "SOURCES.md"],
    )

    sdd_report = load_text(EXAMPLES / "demo-sdd-drift" / "expected-entropy-report.md")
    require_terms(
        "demo-sdd-drift report",
        sdd_report,
        ["SPEC_DRIFT", "UNKNOWN_ROOT", "docs/sdd.md", "src/auth_flow.py", "tests/test_auth_flow.py", "SOURCES.md"],
    )
    advanced_report = load_text(EXAMPLES / "demo-agent-drift-advanced" / "expected-entropy-report.md")
    require_terms(
        "demo-agent-drift-advanced report",
        advanced_report,
        ["SEMANTIC-INSTRUCTION-CLUSTER", "MEMORY-LEAK", "SKILL-BLOAT", "TONE-BEHAVIOR-DRIFT", "session", "SOURCES.md"],
    )
    minor_report = load_text(EXAMPLES / "demo-minor-gc" / "expected-minor-gc-report.md")
    require_terms(
        "demo-minor-gc report",
        minor_report,
        ["AUTO_FIXED", "UNKNOWN_ROOT_SKIP", "scalar", "8000", "8080"],
    )

    memory_report = load_text(EXAMPLES / "demo-memory-drift" / "expected-memory-gc-report.md")
    require_terms(
        "demo-memory-drift report",
        memory_report,
        ["memory-condense", "CURRENT_MEMORY_WRITTEN", "Evidence", "CONFLICT_NEEDS_REVIEW", "memory/current/user-preference.md"],
    )

    review_report = load_text(EXAMPLES / "demo-review-queue" / "expected-review-queue.md")
    require_terms(
        "demo-review-queue report",
        review_report,
        ["review-queue.json", "memory-conflict", "sdd-drift", "options", "recommend", "AskUserQuestion"],
    )


def check_sources_map() -> None:
    sources = load_text(ROOT / "SOURCES.md")
    require_terms(
        "SOURCES.md",
        sources,
        ["skill-protocol", "hook-behavior", "eval-fixtures", "github-release-readiness"],
    )
    require_regex("SOURCES.md", sources, [r"\*\*Status:\*\* `SYNCED`", r"python scripts/run_evals.py"])


def main() -> int:
    check_evals_json()
    check_demo_reports()
    check_sources_map()
    print("OK: context-gc eval fixtures validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
