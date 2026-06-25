#!/usr/bin/env python3
"""Session-level MARK for exported transcripts.

This is the transcript heap counterpart to scripts/mark.py. It is read-only with respect to project
facts: it scans an exported markdown/jsonl/text transcript and writes session findings under
.context-gc/ for human/model judgment. It never compacts or deletes transcript content.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import time

DECISION_RE = re.compile(r"\b(decided|decision|final|agreed|approved|plan|todo|must|never|always)\b|决定|确认|计划|必须|不要", re.I)
TOOL_BLOCK_RE = re.compile(r"(<tool|tool_result|stdout|stderr|```)", re.I)
CONTRADICTION_RE = re.compile(r"\b(no longer|instead|changed|superseded|cancel|不要|改成|废弃|替代)\b", re.I)


def rough_token_count(text: str) -> int:
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    non_cjk = max(0, len(text) - cjk)
    return max(1, cjk + non_cjk // 4) if text else 0


def load_transcript(path: pathlib.Path) -> str:
    if path.suffix.lower() == ".jsonl":
        chunks = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                chunks.append(line)
                continue
            chunks.append(json.dumps(obj, ensure_ascii=False))
        return "\n".join(chunks)
    return path.read_text(encoding="utf-8")


def line_findings(text: str) -> list[dict]:
    lines = text.splitlines()
    findings = []
    seen: dict[str, list[int]] = {}
    tool_run = 0
    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if TOOL_BLOCK_RE.search(stripped):
            tool_run += 1
        else:
            if tool_run >= 40:
                findings.append({
                    "type": "tool-result-bloat",
                    "status": "NOT_CHECKED",
                    "severity": "low",
                    "line": idx - tool_run,
                    "detail": f"large tool/output block spans ~{tool_run} lines",
                    "needs_judgment": "Replace settled output with a one-line result plus pointer before carrying it forward.",
                })
            tool_run = 0
        if DECISION_RE.search(stripped):
            norm = re.sub(r"\d+", "<num>", stripped.lower())[:100]
            seen.setdefault(norm, []).append(idx)
        if CONTRADICTION_RE.search(stripped) and DECISION_RE.search(stripped):
            findings.append({
                "type": "stale-plan-signal",
                "status": "UNKNOWN_ROOT",
                "severity": "medium",
                "line": idx,
                "detail": f"later turn appears to supersede an earlier plan: `{stripped[:100]}`",
                "needs_judgment": "Preserve the latest decision and archive the superseded plan in a compaction summary.",
            })
        if re.search(r"\b(todo|pending|follow up|待办|未完成)\b", stripped, re.I):
            findings.append({
                "type": "orphaned-session-task",
                "status": "NOT_CHECKED",
                "severity": "low",
                "line": idx,
                "detail": f"task-like line may need closure before compaction: `{stripped[:100]}`",
                "needs_judgment": "Confirm whether this task is done, abandoned, or should be moved to durable memory.",
            })
    for norm, locs in seen.items():
        if len(locs) >= 3:
            findings.append({
                "type": "repeated-session-instruction",
                "status": "NOT_CHECKED",
                "severity": "low",
                "line": locs[0],
                "detail": f"similar decision/instruction repeated at lines {locs[:5]}",
                "needs_judgment": "Collapse repeated discussion into one durable decision statement.",
            })
    return findings


def render_report(name: str, text: str, findings: list[dict]) -> str:
    tokens = rough_token_count(text)
    lines = [
        f"## Session entropy report — {name}",
        "",
        f"Approx transcript budget: ~{tokens} tokens. Findings: {len(findings)}.",
        "Status legend: SYNCED | DRIFTED | NOT_CHECKED | FORK | HISTORICAL | UNKNOWN_ROOT",
        "",
    ]
    if tokens >= 16000:
        lines.append(f"🟡 SESSION-BUDGET             NOT_CHECKED   transcript ~{tokens} tokens → compact transcript")
        lines.append("     → Summarize durable decisions, unresolved questions, and evidence pointers; do not delete evidence silently.")
    for f in findings:
        icon = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(f["severity"], "•")
        lines.append(f"{icon} {f['type'].upper():28} {f['status']:12} line {f.get('line', '?')}")
        lines.append(f"     {f['detail']}")
        lines.append(f"     → {f['needs_judgment']}")
    lines.append("")
    lines.append("Session MARK is read-only. Compaction requires preserving decisions/evidence in a summary or log.")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="MARK an exported session transcript for context rot")
    ap.add_argument("--target", default=".", help="repository where .context-gc output is written")
    ap.add_argument("--transcript", required=True, help="markdown/jsonl/text transcript to scan")
    ap.add_argument("--report-out", help="optional markdown report output path")
    args = ap.parse_args()

    target = pathlib.Path(args.target).resolve()
    transcript = pathlib.Path(args.transcript).resolve()
    if not transcript.exists():
        print(f"FAIL: transcript not found: {transcript}")
        return 1
    text = load_transcript(transcript)
    findings = line_findings(text)

    state = target / ".context-gc"
    state.mkdir(exist_ok=True)
    out = state / "session-findings.json"
    out.write_text(json.dumps({
        "target": target.name,
        "transcript": str(transcript),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "approx_tokens": rough_token_count(text),
        "findings": findings,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    report = render_report(transcript.name, text, findings)
    report_path = pathlib.Path(args.report_out) if args.report_out else state / "session-report.md"
    if not report_path.is_absolute():
        report_path = target / report_path
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"[session-findings.json] {out.relative_to(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
