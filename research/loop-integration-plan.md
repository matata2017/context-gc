# context-gc × Loop Engine 集成开发计划

> 生成时间：2026-06-25
> 状态：Phase 2 进行中（agent-first 核心）。Phase 3（Ralph 接缝）已设计，未动工。
> 关联：`research/context-gc-research.md`（GC 模型）、`SKILL.md`（行为契约）、`SOURCES.md`（写屏障）

## 0. 一句话定位

研究校准后的结论：**context-gc 不是 loop engine，也不该变成 loop engine。** 它是任何
自主循环 / 多智能体编排里那个**确定性的「护栏 + 验证 + 升级打包」下层**。loop engine 负责
调度和多 agent 协作；context-gc 负责「不出错、拦违规、把难题打包好」。

研究依据见 §6。

## 1. 背景与动机

- 软件的「主要用户」正在从人变成 agent（Levie/Karpathy）。一个只能靠人点选的治理工具，对
  自主 agent 等于不存在。
- 自主 agent 常在长任务里不结束会话、不频繁改 context 文件，导致 context-gc 现有的两个触发点
  （PostToolUse dirty-card、Stop reminder）够不着「循环运行中」悄悄长大的漂移。
- 长程 agent 自身的 context/memory 会腐烂（context bloat → distraction → 越跑越笨），这正是
  context-gc 该治、却还没接进 loop 的盲区。

目标：让一个自主 loop 驱动 context-gc，自动消解它**被授权**消解的漂移，只把策略保留给人的部分
升级出去。人不再操作工具，人**设定策略 + 审计留痕**。

## 2. 设计原则（不可动摇）

1. **确定性护栏层，不抢编排。** context-gc 不写任何「编排多 agent」的逻辑——那是 loop engine 的事。
2. **never_auto 是代码级硬地板。** 即便策略 level=full，agent 也碰不了 protected / 删除原件 /
   memory 写入 / 模糊项（recommend=-1）。配置只能放宽 level，删不掉地板。
3. **人拥有边界，agent 在边界内行动。** autonomy 策略写在 config，是委托代理问题的答案。
4. **全程留痕、原件保留。** 每个 agent 自决写 `decisions.jsonl`，原件归档不删，可审计可回滚。
5. **dogfood 自洽。** context-gc 自己的 SOURCES.md / 结构漂了，CI 直接红。

## 3. 三个角色（context-gc 在 loop 里只占这三格）

| 角色 | 学术对应 | 落地接口 | 现状 |
|---|---|---|---|
| A. Verification gate | plan-then-execute 的 verify 拦截 | `gc_tick --gate` | 待 Phase 3 |
| B. Loop 自身 context 压缩 | ACON/AgentFold 的 context-bloat 治理 | `gc_tick --loop-state` | 待 Phase 3 |
| C. 升级任务生产者 | Anthropic「详细 subtask spec」 | `gc_tick --emit-tasks` | 待 Phase 3 |

**差异化（来自 Anthropic 一手经验）**：subagent 失败的头号原因是「任务描述太模糊」。context-gc 的
review-queue item 已带 `summary + evidence + options + recommend` —— 这本身就是一份高质量
subtask spec。我们不自己解模糊漂移，而是把它**打包成 orchestrator 能直接喂给 worker 的、规格完整的
任务**。别人的升级任务是「去看看这个冲突」，我们的是结构化、带证据、带选项的。

## 4. 三层升级模型（对应不同执行者）

```
安全机械漂移（端口/指针/生成态）
  → context-gc 单机确定性自决，无 LLM、无 agent
     （gc_tick --auto / resolve.py --auto）

模糊 / 敏感漂移（memory 冲突、SDD 漂移、recommend=-1）
  → 不再"只能等人"：打包成 loop 任务，交多 agent 解
     researcher 查证 → planner 定 → worker 改 → qa/verify 验
     （gc_tick --emit-tasks，Phase 3）

红线（protected / identity / legal / 删除原件）
  → 永远留人（never_auto 代码 floor 不变）
```

## 5. 分阶段路线图

### Phase 1 — 托管服务基础（已完成）
- 引导式 setup（`init --guided` + setup-draft.json）、安全默认（auto-MARK 开、apply_safe 关）、
  交互式 review 队列、Stop 钩子待决提示、dogfood 自检。
- 产物：`review_queue.py`、`gc_tick` 的前置依赖、demo-review-queue。

### Phase 2 — Agent-first 核心（进行中）
目标：把「默认用户」从人翻成 agent，人是 fallback。

| # | 任务 | 文件 | 状态 |
|---|---|---|---|
| 2.1 | autonomy 策略 + never_auto 代码地板 + policy_class | `_common.py`、`review_queue.py` | ✅ 完成 |
| 2.2 | init 生成 `autonomy:` 配置块（默认 assist） | `init_context_gc.py` | ✅ 完成 |
| 2.3 | `resolve.py`：非交互策略化自决 + decisions.jsonl 审计 + `--log` | `scripts/resolve.py`（新） | ⏳ 进行中 |
| 2.4 | `gc_tick.py`：loop/agent 入口，内部产出**结构化 tick 结果对象** | `scripts/gc_tick.py`（新） | ⬜ 待办 |
| 2.5 | MCP surface 设计文档 + 桩（不建运行 server） | `references/mcp-surface.md`（新） | ⬜ 待办 |
| 2.6 | SKILL.md 重构：agent-first 主路径、human fallback | `SKILL.md` | ⬜ 待办 |
| 2.7 | demo-agent-autonomy + evals + dogfood + 文档 | `examples/`、`evals/`、`validate_*` | ⬜ 待办 |
| 2.8 | 全量验证 + 清理 demo 状态 | — | ⬜ 待办 |

**2.4 关键约束**：gc_tick 必须产出一个结构化结果对象
`{auto_fixed, agent_resolved, escalated, pending}`，使 Phase 3 的
`--gate / --loop-state / --emit-tasks` 都只是这个对象上的**薄适配器**，避免返工。

### Phase 3 — Ralph / Loop 接缝（已设计，未动工）
用户已选定三个接缝（按价值排序）：

1. **`gc_tick --gate`（漂移闸门）** — 用作 loop 的 `verify_cmd`：任务做完跑一次，引入了不可自动消的
   漂移 → exit 1 → loop 标 verify_failed 重试。最通用，任何 verify_cmd 引擎都能用。
2. **`gc_tick --loop-state CONTEXT.md PROGRESS.md`（治循环自身记忆）** — 把 100 轮的 append-only
   PROGRESS.md 压成「决策 + 证据」，CONTEXT.md 查过期任务态，防止 loop 被旧上下文污染。
3. **`gc_tick --emit-tasks`（升级成多 agent 任务）** — 把 review-queue 的模糊/敏感升级项写成
   Ralph `queue.md` 的 YAML 任务，交 orchestrator 的 research→plan→execute→verify 解决。

未选：「后台 hygiene 任务」（和 gate 重叠）。

### Phase 4 — MCP server（远期）
把 Phase 2.5 设计的接口实装成运行的 MCP server（`context_gc.tick/review_queue/resolve/profile`）。
CLI 是 ground truth，MCP 是其封装。「没 API/MCP 等于不存在」的终局形态。

## 6. 研究依据（校准设计的关键来源）

- **Anthropic 多 agent 系统**（一手）：orchestrator-worker；详细 subtask spec 防重复/遗漏；
  外部记忆 + 200k 前存计划 + 阶段性摘要；输出落盘传引用避免「传话游戏」退化；checkpoint/resume；
  LLM-as-judge rubric 验证。→ 印证 context-gc 该当「验证 + 打包」层，别自己编排。
- **plan-then-execute 安全架构**（arXiv 2509.08646）：verification 拦截不安全 tool call + 升级 HITL；
  护栏 LLM 不可绕过。→ 印证 never_auto floor 的设计。
- **长程 context 管理**（ACON / AgentFold / Sculptor / MemAgent，2025）：context bloat 致
  distraction，需分段/摘要/压缩/遗忘/更新。→ 印证角色 B（治 loop 自身记忆）的价值。
- **loop 架构通识**（Oracle / Google Cloud / 编排模式综述）：分层停止条件；多数系统从单 agent 起，
  复杂度真需要才上多 agent。→ 印证 context-gc 不该过度工程成 loop engine。

完整研究笔记见会话记忆 `loop-engine-multiagent-research`。

## 7. 验收标准（Phase 2 完成的定义）

- agent 只消解 autonomy 策略 + 代码 floor 允许的项；其余升级到队列。
- 每个 agent 自决写审计日志、原件不删、可回滚。
- `gc_tick` 非交互、可被任何 loop 驱动；待决项累积等下一次人触达。
- 人路径（setup/review）作为 fallback 仍可用；MCP 接口已设计、server 缓做。
- dogfood 自检 + 全部 validator 绿。
