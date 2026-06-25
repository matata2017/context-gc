# context-gc MCP surface (design + deferred server)

> 状态：接口设计稳定，server 实现远期再做。CLI 是当前 ground truth；MCP 只是其封装。
> 对应实现：`scripts/gc_tick.py`、`scripts/review_queue.py`、`scripts/resolve.py`。

context-gc 不是 loop engine，而是给 loop engine / 多 agent 编排用的**确定性护栏层**。MCP 表面只暴露四个工具，分别对应「跑一轮」「看队列」「解一项」「读画像」。

## 设计原则

1. **只读/可写分离。** `tick`、`profile` 可改变磁盘状态；`review_queue` 只读；`resolve` 只写 policy 允许的内容。
2. **永远返回结构化结果。** 每个工具输出 JSON Schema 固定的对象，loop engine 直接消费，不需要解析自然语言。
3. **不替 loop 决定。** 模糊/敏感/红线项升级到 `review-queue.json`；`--emit-tasks` 适配器负责把它转成 Ralph 等编排器的任务格式，而不是在 MCP 里自己编排。
4. **与 CLI 1:1。** MCP 参数名、字段名和 CLI flag 保持一致；server 代码只是薄封装。

## Tools

### `context_gc.tick`

运行一次治理 tick。等效于：

```bash
python scripts/gc_tick.py --target <target> [--quiet]
```

**输入**
```json
{
  "target": ".",
  "quiet": false
}
```

**输出 (TickResult)**
```json
{
  "tick_at": "2026-06-25 23:45:22",
  "target": "demo-memory-drift",
  "auto_fixed": 0,
  "agent_resolved": 0,
  "escalated": 1,
  "pending": 1,
  "policy_level": "assist",
  "steps_rc": {
    "mark": 0,
    "minor_gc": 0,
    "review_queue": 0,
    "resolve": 0
  },
  "audit": ".context-gc/decisions.jsonl",
  "queue": ".context-gc/review-queue.json"
}
```

**调用方应如何处理**
- `escalated == 0 && pending == 0`：本轮无残留，继续主任务。
- `escalated > 0`：有项触达 never_auto 或 policy 保留给人的边界，loop 应调用 `context_gc.review_queue` 获取详细任务 spec，再决定是自己编排多 agent 解，还是暂停等人。
- `steps_rc` 任一非 0：子进程异常，loop 应把本次 tick 标记为 `verify_failed` 或重试。

---

### `context_gc.review_queue`

读取当前待决决策队列。等效于：

```bash
python scripts/review_queue.py --target <target> [--json-only]
```

**输入**
```json
{
  "target": "."
}
```

**输出**
```json
{
  "open": 1,
  "items": [
    {
      "id": "memory-conflict-83f0",
      "kind": "memory-conflict",
      "status": "open",
      "summary": "Memory conflict: profile says dark mode, mid-term says light mode",
      "evidence": ["memory/profile.md:3", "memory/midterm-2026-05.md:7"],
      "options": [
        {"label": "Keep profile (dark)", "action": {"op": "set_current_memory", "from": "memory/profile.md"}},
        {"label": "Keep mid-term (light)", "action": {"op": "set_current_memory", "from": "memory/midterm-2026-05.md"}},
        {"label": "Both valid — mark FORK", "action": {"op": "mark_fork"}}
      ],
      "recommend": -1,
      "policy_class": "sensitive"
    }
  ]
}
```

每个 item 都是一份可直接喂给 worker agent 的 subtask spec：`summary` 是目标，`evidence` 是上下文，`options` 是允许的输出，`recommend` 是置信度，`policy_class` 告诉编排器该用哪种 worker。

---

### `context_gc.resolve`

在 autonomy policy 内执行一个决策。等效于：

```bash
python scripts/resolve.py --target <target> --item <id> --choice <N>
```

**输入**
```json
{
  "target": ".",
  "item": "memory-conflict-83f0",
  "choice": 0
}
```

**输出**
```json
{
  "ts": "2026-06-25 23:45:22",
  "item": "memory-conflict-83f0",
  "kind": "memory-conflict",
  "choice": 0,
  "action": {"op": "set_current_memory", "from": "memory/profile.md"},
  "by": "agent",
  "policy_level": "assist",
  "applied": false,
  "detail": "op `set_current_memory` is human-reserved or no SOURCES domain matched; not auto-executed",
  "reversible": true,
  "originals_kept": []
}
```

`applied: false` 且 detail 提到 policy/floor 时，说明该项仍在 never_auto 范围内，必须升级给人。

---

### `context_gc.profile`

读取最近一次 tick 的画像与统计，不跑新 tick。等效于读取 `.context-gc/tick.json` 与 `.context-gc/findings.json` 的聚合。

**输入**
```json
{
  "target": "."
}
```

**输出**
```json
{
  "last_tick": "2026-06-25 23:45:22",
  "policy_level": "assist",
  "counts": {
    "auto_fixed": 0,
    "agent_resolved": 0,
    "escalated": 1,
    "pending": 1
  },
  "top_kinds": ["memory-conflict"]
}
```

## 错误处理

所有工具在失败时返回如下结构（HTTP/MCP error object）：

```json
{
  "error": true,
  "message": "target is not a directory: /not/a/dir",
  "code": "invalid_target"
}
```

## 与 Ralph / Loop 引擎的接缝 (Phase 3)

这三个适配器**不是**新 MCP 工具，而是基于上述四个工具的组合：

- **`verify_cmd`**: loop 在任务完成后调用 `context_gc.tick`。若 `escalated > 0` 或 `steps_rc` 异常 → 标 `verify_failed`。
- **context compaction**: loop 把自身 `CONTEXT.md` / `PROGRESS.md` 路径传给一个 future `--loop-state` flag；该 flag 底层仍调 `context_gc.tick` 并消费 `TickResult`。
- **emit-tasks**: `--emit-tasks` 读取 `review_queue` 输出，把 `recommend < 0` 或 `policy_class: sensitive` 的 item 写成 Ralph `queue.md` YAML。

## Deferred: MCP server 实现

server 启动后只做一件事：把上面四个工具映射到 CLI 子进程调用。建议文件 `scripts/mcp_server.py`，使用 `mcp.server.Server` 标准模板。Deferred 原因：

1. CLI 已经满足 loop 集成（任何 loop 都能调用命令行）。
2. 等接口被真实 loop 调用并稳定后，再建 server 避免白做。
3. server 需要依赖 `mcp` SDK，会改变安装体验；当前 skill 是零依赖 Python。

当开始实现时，复用 `_common.py` 中的 `load_autonomy_policy` 与 `agent_may_resolve` 做输入校验，不要重复 policy 逻辑。
