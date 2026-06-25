#!/usr/bin/env python3
"""context-gc → Hermes (Ralph Loop) 适配器。

Hermes 是状态机驱动的多 agent 编排器，使用 YAML 任务队列。此适配器把 context-gc
的 TickResult 和 review-queue 翻译成 Hermes 能消费的格式，让你一行命令接入。

三个子命令对应三种集成角色：

  python scripts/adapters/hermes_adapter.py gate        → Hermes 的 verify_cmd
  python scripts/adapters/hermes_adapter.py emit-tasks  → 把升级项写成 Hermes 任务
  python scripts/adapters/hermes_adapter.py compact     → 压缩 loop 自身 context

使用示例见 references/architecture.md §"Hermes 集成实例"。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent.parent


def _tick(target: pathlib.Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(HERE / "gc_tick.py"), "--target", str(target)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return {"error": proc.stdout}


def _queue(target: pathlib.Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(HERE / "review_queue.py"), "--target", str(target)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    qpath = target / ".context-gc" / "review-queue.json"
    if qpath.exists():
        return json.loads(qpath.read_text(encoding="utf-8"))
    return {"open": 0, "items": []}


# -- gate: Hermes verify_cmd -------------------------------------------------

def cmd_gate(target: pathlib.Path) -> int:
    """作为 Hermes 的 verify_cmd——任务完成后跑一次，有未消的漂移就 exit 1。

    Hermes 配置示例:
        verify_cmd: "python scripts/adapters/hermes_adapter.py gate --target ."
    """
    result = _tick(target)
    escalated = result.get("escalated", 0)
    steps_rc = result.get("steps_rc", {})

    if any(v != 0 for v in steps_rc.values()):
        print(f"[context-gc] gate: tick pipeline error — {steps_rc}")
        return 1

    if escalated > 0:
        # 有升级项在队列里，gate 失败 → Hermes 标 verify_failed 并重试/升级
        print(f"[context-gc] gate: {escalated} drift item(s) escalated — gate DENIED")
        print(f"  review queue: {result.get('queue', '')}")
        return 1

    print(f"[context-gc] gate: clean — {result.get('auto_fixed', 0)} auto-fixed")
    return 0


# -- emit-tasks: 升级项 → Hermes 任务 YAML ------------------------------------

def _hermes_task(item: dict, index: int) -> str:
    """把一个 review-queue item 翻译成 Hermes queue.md 的一个任务条目。"""
    kind = item.get("kind", "drift")
    summary = item.get("summary", "")
    evidence = item.get("evidence", [])
    options = item.get("options", [])

    opt_lines = "\n".join(f"      - {o['label']}" for o in options)
    ev_lines = "\n".join(f"      - {e}" for e in evidence)

    return f"""  - id: drift-{index}
    type: investigate-and-resolve
    priority: medium
    source: context-gc
    summary: "[context-gc] [{kind}] {summary}"
    context:
      evidence:
{ev_lines}
      options:
{opt_lines}
      recommendation: {"none (ambiguous)" if item.get("recommend", -1) < 0 else f"option {item['recommend']}"}
    assignee: researcher
    verify:
      cmd: "python scripts/adapters/hermes_adapter.py gate --target ."
"""


def cmd_emit_tasks(target: pathlib.Path, output: str) -> int:
    """把 review-queue 中 agent 消不掉的项，写成 Hermes queue.md 任务。

    Hermes 配置示例:
        pre_tick_cmd: "python scripts/adapters/hermes_adapter.py emit-tasks --target . --output queue.md"
    """
    # 先跑一次 tick 确保队列最新
    _tick(target)
    queue = _queue(target)
    items = [it for it in queue.get("items", []) if it.get("status") == "open"]
    if not items:
        print("[context-gc] emit-tasks: queue is empty — nothing to emit")
        return 0

    header = f"# context-gc drift tasks — generated {time.strftime('%Y-%m-%d %H:%M:%S')}\n\ntasks:\n"
    tasks = "\n".join(_hermes_task(it, i) for i, it in enumerate(items, 1))
    out_path = pathlib.Path(output)
    existing = ""
    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8")
        # 追加到现有 queue.md 末尾（不覆盖 Hermes 自己的任务）
        if "context-gc drift tasks" in existing:
            # 替换旧的 context-gc 任务块
            marker = "# context-gc drift tasks"
            idx = existing.find(marker)
            next_section = existing.find("\n# ", idx + len(marker))
            if next_section == -1:
                next_section = len(existing)
            existing = existing[:idx] + existing[next_section:]

    out_path.write_text(existing + "\n" + header + tasks, encoding="utf-8")
    print(f"[context-gc] emit-tasks: wrote {len(items)} task(s) → {output}")
    return 0


# -- compact: 压缩 loop 自身 context ------------------------------------------

def cmd_compact(target: pathlib.Path, context_file: str, progress_file: str) -> int:
    """压缩 loop 自身的 append-only 记忆——CONTEXT.md 和 PROGRESS.md。

    用法: hermes_adapter.py compact --target . --context CONTEXT.md --progress PROGRESS.md
    """
    ctx = pathlib.Path(context_file)
    prg = pathlib.Path(progress_file)
    report_lines = [f"# Loop state compaction — {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]

    # 1) 压缩 CONTEXT.md：移除过期状态标记，保留当前决策
    if ctx.exists():
        ctx_text = ctx.read_text(encoding="utf-8")
        decisions: list[str] = []
        unresolved: list[str] = []
        current_section = ""
        for line in ctx_text.splitlines():
            s = line.strip()
            if s.startswith("## "):
                current_section = s
            if s.startswith("Decision:") or s.startswith("决策:"):
                decisions.append(s)
            if s.startswith("TODO") or s.startswith("TODO:"):
                unresolved.append(f"{current_section} → {s}" if current_section else s)

        # 写入压缩版：当前决策 + 未解决问题
        compact = [
            f"# Compacted CONTEXT.md — {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Durable decisions",
            *(f"- {d}" for d in decisions[-20:]),  # 只保留最近 20 条
            "",
            "## Unresolved",
            *(f"- {u}" for u in unresolved[-10:]),  # 只保留最近 10 条
            "",
            f"_(compacted from {len(ctx_text.splitlines())} lines by context-gc)_",
        ]
        compacted_path = ctx.with_suffix(".compacted.md")
        compacted_path.write_text("\n".join(compact) + "\n", encoding="utf-8")
        report_lines.append(f"- `{context_file}`: {len(ctx_text.splitlines())} → {len(compact)} lines → `{compacted_path.name}`")
    else:
        report_lines.append(f"- `{context_file}`: not found, skipped")

    # 2) 压缩 PROGRESS.md：合并重复状态行
    if prg.exists():
        prg_text = prg.read_text(encoding="utf-8")
        lines = prg_text.splitlines()
        seen = set()
        unique = []
        for line in lines:
            h = hash(line.strip())
            if h not in seen:
                seen.add(h)
                unique.append(line)
        compacted_prg = prg.with_suffix(".compacted.md")
        compacted_prg.write_text("\n".join(unique) + "\n", encoding="utf-8")
        report_lines.append(f"- `{progress_file}`: {len(lines)} → {len(unique)} lines (deduped)")

    print("\n".join(report_lines))
    return 0


# -- main --------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="context-gc → Hermes adapter")
    sp = ap.add_subparsers(dest="cmd")

    g = sp.add_parser("gate", help="Hermes verify_cmd — exit 1 if drift remains")
    g.add_argument("--target", default=".")

    e = sp.add_parser("emit-tasks", help="Write escalated drift as Hermes queue.md tasks")
    e.add_argument("--target", default=".")
    e.add_argument("--output", default="queue.md", help="Hermes task queue file")

    c = sp.add_parser("compact", help="Compact loop CONTEXT.md and PROGRESS.md")
    c.add_argument("--target", default=".")
    c.add_argument("--context", default="CONTEXT.md")
    c.add_argument("--progress", default="PROGRESS.md")

    args = ap.parse_args()
    target = pathlib.Path(args.target).resolve()

    if args.cmd == "gate":
        return cmd_gate(target)
    if args.cmd == "emit-tasks":
        return cmd_emit_tasks(target, args.output)
    if args.cmd == "compact":
        return cmd_compact(target, args.context, args.progress)

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
