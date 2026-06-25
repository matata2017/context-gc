#!/usr/bin/env python3
"""context-gc MCP server — 标准 MCP 协议 stdio server。

把 gc_tick / review_queue / resolve / profile 四个能力暴露为 MCP 工具，
任何 MCP 兼容的 agent 都能直接调用。

启动方式（配到 .mcp.json 或 Claude Code MCP 配置里）：
  {
    "mcpServers": {
      "context-gc": {
        "command": "python",
        "args": ["<path>/scripts/mcp_server.py", "--project-dir", "/path/to/your/project"]
      }
    }
  }

依赖：无。纯 stdlib + JSON-RPC stdio。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PROJECT_DIR = pathlib.Path.cwd()


# -- JSON-RPC 2.0 工具定义 ---------------------------------------------------

TOOLS = [
    {
        "name": "tick",
        "description": "运行一次 context-gc 治理 tick。mark → minor_gc → review_queue → resolve → analyze。返回 TickResult 结构化 JSON。永不阻塞。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "quiet": {"type": "boolean", "description": "只打印一行摘要（默认 false，返回完整 JSON）"},
            },
            "required": [],
        },
    },
    {
        "name": "review_queue",
        "description": "读取当前待决漂移决策队列。每个 item 自带 summary、evidence、options、recommend，可直接喂给 worker agent。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "resolve",
        "description": "在 autonomy policy 内执行一个决策。item 和 choice 来自 review_queue 输出。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "queue item id"},
                "choice": {"type": "integer", "description": "option index (0-based)"},
            },
            "required": ["item", "choice"],
        },
    },
    {
        "name": "profile",
        "description": "读取最近一次 tick 的画像与统计，不跑新 tick。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# -- CLI 调用 ----------------------------------------------------------------

def _run(script: str, *args: str) -> dict | str:
    try:
        proc = subprocess.run(
            [sys.executable, str(HERE / script), "--target", str(PROJECT_DIR), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        out = proc.stdout.strip()
        try:
            return json.loads(out.splitlines()[-1] if "\n" in out else out)
        except Exception:
            return out
    except Exception as exc:
        return {"error": str(exc)}


# -- MCP stdio loop ----------------------------------------------------------

def _reply(request_id: str | int, result) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(request_id: str | int | None, code: int, message: str) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_request(msg: dict) -> None:
    rid = msg.get("id")
    method = msg.get("method", "")

    if method == "initialize":
        return _reply(rid, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "context-gc", "version": "1.0"},
        })

    if method == "notifications/initialized":
        return  # no reply

    if method == "tools/list":
        return _reply(rid, {"tools": TOOLS})

    if method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "tick":
            quiet = arguments.get("quiet", False)
            args = ["--quiet"] if quiet else []
            result = _run("gc_tick.py", *args)
            return _reply(rid, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

        if tool_name == "review_queue":
            _run("review_queue.py", "--json-only")
            qpath = PROJECT_DIR / ".context-gc" / "review-queue.json"
            if qpath.exists():
                result = json.loads(qpath.read_text(encoding="utf-8"))
            else:
                result = {"open": 0, "items": []}
            return _reply(rid, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

        if tool_name == "resolve":
            item = arguments.get("item", "")
            choice = arguments.get("choice", 0)
            result = _run("resolve.py", "--item", str(item), "--choice", str(choice))
            return _reply(rid, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else str(result)}]})

        if tool_name == "profile":
            tick_path = PROJECT_DIR / ".context-gc" / "tick.json"
            if tick_path.exists():
                result = json.loads(tick_path.read_text(encoding="utf-8"))
            else:
                result = {"last_tick": None, "message": "No tick data yet. Run tick first."}
            return _reply(rid, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

        return _error(rid, -32601, f"Unknown tool: {tool_name}")

    return _error(rid, -32601, f"Unknown method: {method}")


def main() -> int:
    global PROJECT_DIR

    # --project-dir 指定目标项目路径
    for i, arg in enumerate(sys.argv):
        if arg == "--project-dir" and i + 1 < len(sys.argv):
            PROJECT_DIR = pathlib.Path(sys.argv[i + 1]).resolve()
        if arg == "--project-dir=":
            PROJECT_DIR = pathlib.Path(arg.split("=", 1)[1]).resolve()

    # 只写 stderr 日志，stdout 是 MCP 协议通道
    sys.stderr.write(f"[context-gc MCP] project: {PROJECT_DIR}\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            handle_request(msg)
        except json.JSONDecodeError:
            _error(None, -32700, "Parse error")
        except Exception as exc:
            _error(None, -32603, str(exc))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
