#!/usr/bin/env python3
"""Regression tests for detector false positives found on real repos.

Not a full unit suite — a focused red gate for the two FP classes a real-repo (Chinese, doc-heavy)
audit surfaced, so they cannot silently come back:

  1. orphan-reference flagged example paths inside fenced code blocks and `<placeholder>` paths.
  2. review_queue surfaced findings whose observation-site file was deleted by an earlier sweep.

Run: python scripts/test_detectors.py   (exit 0 = pass, 1 = fail). Wired into CI via validate.yml.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mark  # noqa: E402
import review_queue  # noqa: E402


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def test_orphan_skips_fenced_and_placeholder() -> None:
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "doc.md").write_text(
        "# Doc\n"
        "[real orphan](really-missing.md)\n\n"        # real → must stay flagged
        "[placeholder](research/<topic>.md)\n\n"       # <placeholder> → must be skipped
        "```markdown\n"
        "[fenced example](examples/fenced-missing.md)\n"  # inside fence → must be skipped
        "```\n",
        encoding="utf-8",
    )
    flagged = {f["detail"] for f in mark.check_orphans(d, [d / "doc.md"])}
    if not any("really-missing.md" in s for s in flagged):
        fail("orphan check should still flag a real missing link")
    if any("<topic>" in s for s in flagged):
        fail("orphan check must skip <placeholder> paths")
    if any("fenced-missing.md" in s for s in flagged):
        fail("orphan check must skip refs inside fenced code blocks")


def test_review_queue_drops_findings_for_deleted_files() -> None:
    d = pathlib.Path(tempfile.mkdtemp())
    (d / ".context-gc").mkdir()
    (d / "lives.md").write_text("# still here\n", encoding="utf-8")
    findings = [
        {"type": "contradiction", "status": "DRIFTED", "severity": "high",
         "file": "lives.md", "line": 1, "detail": "claim in a file that exists"},
        {"type": "contradiction", "status": "DRIFTED", "severity": "high",
         "file": "gone.md", "line": 1, "detail": "claim in a file a sweep deleted"},
    ]
    (d / ".context-gc" / "findings.json").write_text(
        json.dumps({"findings": findings}), encoding="utf-8")
    queue = review_queue.build_queue(d)
    ev_files = {e.split(":", 1)[0] for it in queue for e in it.get("evidence", [])}
    if "lives.md" not in ev_files:
        fail("review queue should keep findings whose file still exists")
    if "gone.md" in ev_files:
        fail("review queue must drop findings whose observation-site file was deleted")


def main() -> int:
    test_orphan_skips_fenced_and_placeholder()
    test_review_queue_drops_findings_for_deleted_files()
    print("OK: detector FP regressions pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
