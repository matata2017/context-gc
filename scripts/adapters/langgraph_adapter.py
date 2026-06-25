#!/usr/bin/env python3
"""context-gc → LangGraph 适配器。

LangGraph 的图由节点（函数 state -> state）和条件边组成，commit 前用 interrupt() 做人审。
context-gc 的 `gc_tick --gate` + review-queue 升级是同一个模式——所以 context-gc 可以作为
LangGraph 图里的一个**验证节点**接进去，就像它能接 Hermes 一样。

设计原则（next-phase-design.md）：**学 LangGraph 的设计，不进它的笼子。**
- 本文件不 import langgraph，不引入任何依赖——context-gc 是零依赖 sidecar。
- 它提供一个纯函数节点 + 一段路由建议，用户把它粘进自己的图。
- 节点调 gc_tick 子进程（和 hermes_adapter 一样），把 TickResult 写进 LangGraph state。

两种用法：

  # 1) 打印一个可直接粘进 LangGraph 图的节点模板
  python scripts/adapters/langgraph_adapter.py template

  # 2) 直接当 verify 节点跑一次（CI / 测试用），返回 gate 结果 JSON
  python scripts/adapters/langgraph_adapter.py gate --target .
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

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


def cmd_gate(target: pathlib.Path) -> int:
    """当 LangGraph 验证节点跑一次：返回适合驱动条件边的 gate 结果。

    LangGraph 条件边读 `decision` 字段：
      - "clean"    → 继续下一个节点
      - "escalate" → 路由到一个 interrupt() 节点做人审
      - "error"    → 路由到错误处理
    """
    result = _tick(target)
    escalated = int(result.get("escalated", 0))
    steps_rc = result.get("steps_rc", {})

    if any(v != 0 for v in steps_rc.values()):
        decision = "error"
    elif escalated > 0:
        decision = "escalate"
    else:
        decision = "clean"

    out = {
        "decision": decision,
        "escalated": escalated,
        "pending": int(result.get("pending", 0)),
        "auto_fixed": int(result.get("auto_fixed", 0)),
        "scope": result.get("scope"),
        "scope_note": result.get("scope_note"),
        "queue": result.get("queue", ".context-gc/review-queue.json"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if decision != "clean" else 0


TEMPLATE = '''\
# --- context-gc verification node for LangGraph -------------------------------
# Paste this into your graph. It has NO langgraph-specific imports beyond what your
# graph already uses, and NO context-gc dependency — it shells out to gc_tick.
# context-gc stays a zero-dependency sidecar; this is just glue you own.

import json, subprocess, sys
from pathlib import Path

CONTEXT_GC = Path("~/.claude/skills/context-gc").expanduser()  # adjust to your install

def context_gc_verify(state: dict) -> dict:
    """LangGraph node: run a governance tick, write the gate decision into state.

    Route on state["context_gc"]["decision"]:
      "clean"    -> continue
      "escalate" -> a node that calls interrupt() for human review of review-queue.json
      "error"    -> error handling
    """
    proc = subprocess.run(
        [sys.executable, str(CONTEXT_GC / "scripts/adapters/langgraph_adapter.py"),
         "gate", "--target", state.get("repo_path", ".")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    try:
        gate = json.loads(proc.stdout)
    except Exception:
        gate = {"decision": "error", "raw": proc.stdout}
    return {**state, "context_gc": gate}

def route_after_verify(state: dict) -> str:
    """Conditional-edge function: map the gate decision to the next node name."""
    return state.get("context_gc", {}).get("decision", "error")

# Wire it up:
#   graph.add_node("context_gc_verify", context_gc_verify)
#   graph.add_node("human_review", <a node that calls interrupt()>)
#   graph.add_conditional_edges("context_gc_verify", route_after_verify, {
#       "clean": "next_step",
#       "escalate": "human_review",
#       "error": "handle_error",
#   })
# ------------------------------------------------------------------------------
'''


def cmd_template() -> int:
    print(TEMPLATE)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="context-gc → LangGraph adapter")
    sp = ap.add_subparsers(dest="cmd")

    g = sp.add_parser("gate", help="run a tick as a verify node; print gate decision JSON")
    g.add_argument("--target", default=".")

    sp.add_parser("template", help="print a paste-ready LangGraph node + routing function")

    args = ap.parse_args()
    if args.cmd == "gate":
        return cmd_gate(pathlib.Path(args.target).resolve())
    if args.cmd == "template":
        return cmd_template()
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
