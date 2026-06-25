# context-gc — 项目架构与开发计划

> 2026-06-26 · Phase 2 完成 · Phase 3 已设计

## 一句话

**context-gc 是 agent 基础设施里的确定性护栏层。** 它不编排多 agent，不抢决策权，不烧 LLM token——
只做三件事：检测漂移（MARK）、自动修复（Minor GC）、升级打包（review queue）。任何 loop engine / 多 agent 编排器 / 自主 agent 都能接入。

---

## 1. 项目定位

### 1.1 我们解决什么问题

agent 跑得够久一定会遇到这些问题：

| 问题 | 表现 |
|---|---|
| **文档漂移** | 代码改了端口为 8080，README 写了半年 8000 |
| **SDD 漂移** | 需求变了，规格书还写密码登录，代码已是 OAuth |
| **配置漂移** | 本地 docker-compose 和生产 k8s config 分道扬镳 |
| **agent 上下文腐烂** | CLAUDE.md / SOUL / skills / memory 累积矛盾指令 |
| **记忆漂移** | 长期记忆写 "concise"，画像写 "verbose"，agent 不知该信谁 |
| **loop 自身腐烂** | 100 轮的 PROGRESS.md 堆满过时 TODOs 和已取消计划 |
| **知识库膨胀** | 同一事实复制在 5 个文件里，各自漂移 |

### 1.2 为什么不是文档 linter 的事

Vale、markdownlint、lychee 是**扫描器**——它们产出证据。context-gc 是**收集器协议**包裹它们之上：
找根 → 追溯声明 → 确认清理 → 记录 `SOURCES.md`，让同样的漂移下次检测零成本。

### 1.3 核心隐喻：垃圾回收

```
┌───────────┐    ┌───────────┐    ┌───────────┐
│  MARK     │ →  │  SWEEP    │ →  │  BARRIER  │
│ (诊断)    │    │ (治理)    │    │ (预防)    │
│ 只读      │    │ 确认后写入 │    │SOURCES.md │
└───────────┘    └───────────┘    └───────────┘
```

| GC 概念 | 上下文熵 |
|---|---|
| **根 (Root)** | 事实的权威来源（代码/配置/CLAUDE.md） |
| **可达 (Live)** | 追溯到根的声明，且仍匹配 |
| **垃圾 (Garbage)** | 过时、孤立、矛盾、重复 |
| **标记 (Mark)** | 找根 → 追溯声明 → 标记垃圾（只读） |
| **清除 (Sweep)** | 调和/删除/压缩（确认后才写） |
| **写屏障 (Write barrier)** | `SOURCES.md`——记录根↔副本关系，下次轻量重检 |

---

## 2. 架构设计

### 2.1 设计模式组合

context-gc 的架构由四个经典设计模式组合而成：

```
 ┌──────────────────────────────────────────────────┐
 │             .context-gc/  (BLACKBOARD)            │
 │                                                  │
 │  dirty.jsonl         ← hook 写入（文件变更）       │
 │  findings.json       ← mark agent 写入（检测结果）  │
 │  patterns.jsonl      ← resolve agent 写入（模式库） │
 │  decisions.jsonl     ← resolve agent 写入（审计）   │
 │  review-queue.json   ← 聚合待决项                  │
 │  tick.json           ← 每次 tick 的结构化结果      │
 └──────────┬───────────────────────────────────────┘
            │
   ┌────────┼────────┐
   ▼        ▼        ▼
┌──────┐ ┌──────┐ ┌──────┐
│ MARK │ │RESOLVE│ │HUMAN │
│Agent │ │Agent  │ │      │
│(OBSERVER)│(STRATEGY)│(FALLBACK)│
│ 只读扫描 │ 策略内自决│ 升级决策  │
└──────┘ └───────┘ └──────┘
   ▲
   │  FEEDBACK LOOP
   │  patterns.jsonl → 下次 MARK 自动识别已知模式
```

| 模式 | 对应 | 作用 |
|---|---|---|
| **Blackboard** 黑板 | `.context-gc/` | 所有 agent 共用一个状态目录。任何人写，任何人读。团队知识不私藏 |
| **Observer** 观察者 | MARK agent | 监听文件变更（hook dirty-card）→ 触发扫描。只读不写，永不主动编辑 |
| **Strategy** 策略 | autonomy policy | 用户配置 "agent 能自决什么级别"，agent 执行。换项目换策略，不改代码 |
| **Feedback Loop** 闭环 | patterns.jsonl | 每次成功自决/修复 → 沉淀为 pattern → 下次 MARK 自动分类 → 更少 UNKNOWN_ROOT |

### 2.2 Sidecar 模式：怎么接入任何团队

context-gc 以 **Sidecar 模式** 接入已有 agent 团队——不替换现有 agent，不抢编排权，只共享文件系统和黑板书。

```
┌──────────────────────────────────────┐
│          同一个 Git 仓库              │
│                                      │
│  ┌──────────┐      ┌──────────────┐  │
│  │ 开发 agent │      │ context-gc   │  │
│  │ (任何框架) │      │ (Sidecar)    │  │
│  │          │      │              │  │
│  │ 写代码    │      │ 读文件        │  │
│  │ 改配置    │      │ 写 .context-gc│  │
│  │ 写文档    │      │ 永不编辑项目文件│  │
│  └──────────┘      └──────────────┘  │
│       │                   │          │
│       ▼                   ▼          │
│  ┌────────────────────────────────┐  │
│  │        .context-gc/ 黑板       │  │
│  │   (共享状态，不共享编排权)      │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

**四级接入——从零成本到深度集成：**

| 级别 | 接入方式 | 适用场景 | 成本 |
|---|---|---|---|
| **L0: CLI** | `python scripts/gc_tick.py --target . --quiet` | 任何 agent 框架（bash/Node/Python/Rust） | 一行命令 |
| **L1: Hook** | 安装 `.claude/settings.json` hooks | Claude Code 团队 | 复制一个 JSON |
| **L2: MCP** | `context_gc.tick()` / `.review_queue()` / `.resolve()` / `.profile()` | MCP 兼容框架（Claude、Continue、Cline） | 标准协议 |
| **L3: Loop Adapter** | `--gate` / `--loop-state` / `--emit-tasks` | Ralph、LangGraph、CrewAI 等编排器 | 薄适配器封装 |

**为什么 Sidecar 是对的选择：**

| 对比 | 中心化服务 | 嵌入式库 | Sidecar（我们的选择） |
|---|---|---|---|
| 部署 | 需要运维 server | 绑语言 | 无——就是 Python 脚本 |
| 框架绑定 | 无 | 绑定 import 的语言 | 无——CLI 通吃 |
| 状态共享 | 网络调用 | 内存 | 文件系统（git 可版本控制） |
| 故障隔离 | 服务挂了全停 | 抛异常影响主流程 | 子进程隔离，挂了不影响主 agent |

### 2.3 Hermes 集成实例（Sidecar 实战）

以接入 Hermes（Ralph Loop 实现）为例——三个适配器命令，不改 Hermes 一行代码：

```
Hermes 的 YAML 任务循环                       context-gc (Sidecar)
═══════════════════════                      ═════════════════════
                                             
  ┌──────────┐
  │ 读取任务  │ ← queue.md
  └────┬─────┘
       ▼
  ┌──────────┐
  │ 执行任务  │ (researcher → planner → worker → qa)
  └────┬─────┘
       ▼
  ┌──────────────────┐      verify_cmd 调用   ┌──────────────────────┐
  │ verify           │ ─────────────────────→ │ hermes_adapter gate  │
  │ (任务做完后检查)  │                        │ → gc_tick            │
  └────┬─────────────┘ ←───────────────────── │ → exit 0 或 exit 1   │
       │                  exit 0: 无漂移      └──────────────────────┘
       │                  exit 1: 有漂移
       │                          → 标 verify_failed
       │                          → 调 emit-tasks
       │                              │
       ▼                              ▼
  ┌──────────────────┐      pre_tick 调用     ┌───────────────────────┐
  │ 下一轮循环        │ ←───────────────────  │ hermes_adapter         │
  │ (读取 queue.md    │   新任务被写入 queue   │ emit-tasks             │
  │  包含 drift 任务)  │                       │ → gc_tick              │
  └──────────────────┘                       │ → queue → queue.md     │
                                             └───────────────────────┘
```

**Hermes 里配三行就接入：**

```yaml
# Hermes config.yaml
loop:
  pre_tick_cmd: "python scripts/adapters/hermes_adapter.py emit-tasks --target . --output queue.md"
  verify_cmd: "python scripts/adapters/hermes_adapter.py gate --target ."
  compact_cmd: "python scripts/adapters/hermes_adapter.py compact --target . --context CONTEXT.md --progress PROGRESS.md"
```

**发生了什么：**

1. 每次 Hermes 任务完成后 → `gate` 跑一次 `gc_tick`。有 agent 消不掉的漂移 → exit 1 → Hermes 标 `verify_failed`
2. Hermes 遇到 `verify_failed` → 调 `emit-tasks` → 升级项从 review-queue.json 翻译成 Hermes 格式的 YAML 任务，追加到 `queue.md`
3. Hermes 下一轮读到这些 drift 任务 → 走 researcher→planner→worker→qa 的多 agent 流程解决
4. 100 轮后 loop 自己记忆腐烂 → `compact` 压缩 CONTEXT.md 和 PROGRESS.md

**适配器代码：** [`scripts/adapters/hermes_adapter.py`](../scripts/adapters/hermes_adapter.py)（三个子命令共 120 行）

### 2.4 数据流——一次 tick 里发生了什么

```bash
python scripts/gc_tick.py --target .
```

```
gc_tick (FACADE —— 一个命令封装全部复杂度)
  │
  ├─ 1. mark.py --dirty-only     →  检测脏文件的漂移候选 → findings.json
  │     (OBSERVER —— 只读，永不编辑)
  │
  ├─ 2. minor_gc.py --apply-safe →  执行预授权安全修复 → minor-gc.json
  │     (STRATEGY —— 仅 apply_safe=true 时生效)
  │     (AUTO_FIXED 的结果 → 自动写 patterns.jsonl)
  │
  ├─ 3. review_queue.py          →  聚合待决项 → review-queue.json
  │     (BLACKBOARD —— 把检测结果翻译成结构化决策)
  │
  └─ 4. resolve.py --auto        →  策略内自决，外升级 → decisions.jsonl
        (STRATEGY —— 每次 applied=true → 自动写 patterns.jsonl)
        (FEEDBACK LOOP —— pattern 积累 → 下次 MARK 自动识别)
```

整个流程**永不阻塞在人上**。待决项留在队列里等人或 loop 来取。

---

## 3. 安全边界（委托代理问题）

context-gc 是 agent-first 设计，但它**不是让 agent 为所欲为**。安全边界通过两层机制实现：

### 3.1 autonomy 策略（用户配置）

```yaml
# .context-gc/config.yml
autonomy:
  level: assist            # off | assist | auto | full
  agent_may_resolve:
    - safe-mechanical      # 端口/指针/生成态 → agent 可自决
  never_auto:              # 硬地板，代码级不可绕过
    - protected            # CLAUDE.md/SOUL/memory/skills/adr/sdd
    - delete               # 任何删除原件的操作
    - memory-condense      # 写入/压缩记忆需要显式 opt-in
    - unknown-root         # recommend=-1 的模糊项
```

### 3.2 never_auto 代码地板

`scripts/_common.py` 里 `NEVER_AUTO_FLOOR` 是代码中硬编码的集合。**即使 `level: full`，agent 也不能碰这些东西。** 用户可以通过配置放宽 `level`，但删除不掉这个地板——只能显式修改 SOURCES 契约来退出特定 domain。

### 3.3 审计链

- `decisions.jsonl` —— 每次 agent 自决都有记录：时间、内容、by whom、是否可逆
- `patterns.jsonl` —— 每次成功修复沉淀为模式，git diff 可审计
- 原件永不删除 —— 归档（archive）或标记 superseded，但不在磁盘上消失

---

## 4. Pattern Learning（自动反馈闭环）

### 4.1 不提问，不等人

agent 不需要被问 "要不要记住"。**所有成功自决/修复 → 自动沉淀为 pattern。**

三个自动来源：

| 来源 | 触发条件 | pattern.source |
|---|---|---|
| minor_gc 预授权修复 | `scalar_sync` 应用成功 | `agent_auto` |
| resolve.py 自决 | 策略内 applied=true | `agent_resolve` |
| SKILL review 人确认 | 人选择了，action 被应用 | `human_resolve` |

### 4.2 pattern 格式

```jsonl
{"id":"port-mismatch-df3a","kind":"scalar-sync","domain":"service-api-port","source":"agent_auto","ts":"2026-06-26","signature":{"root":"docker-compose.yml","copy":"README.md","old":"8000","new":"8080"}}
{"id":"concise-verbose-8b2f","kind":"memory-conflict","domain":"user-verbosity-preference","source":"human_resolve","ts":"2026-06-26","signature":{"terms":["concise","verbose"],"subject":"user-preference:verbosity"}}
```

### 4.3 反馈路径

```
pattern 积累 → mark.py 读取 patterns.jsonl → 已知模式自动分类 → 不再标 UNKNOWN_ROOT → 更少升级、更多自决
```

---

## 5. 当前状态

### Phase 1 — 托管服务基础 ✅
- 引导式 setup（`init --guided`）
- 交互式 review 队列
- Hook 集成（dirty-card, sweep-guard, stop-reminder）
- 安全默认（auto-MARK 开，apply_safe 关）

### Phase 2 — Agent-first 核心 ✅
- autonomy 策略 + never_auto 代码地板
- `resolve.py`：agent 自决 + decisions.jsonl 审计
- `gc_tick.py`：loop/agent 入口，产结构化 TickResult
- MCP surface 设计文档
- SKILL.md 重构为 agent-first 主路径
- `demo-agent-autonomy`：自决 port + 升级 memory conflict
- 28 个 eval 覆盖全场景
- CLAUDE.md, ruff, verify-gc skill, 中文 README

### Phase 3 — Loop 接缝（已设计，未动工）
- `gc_tick --gate` → 作为 loop 的 verify_cmd
- `gc_tick --loop-state` → 治 loop 自身 context 腐烂
- `gc_tick --emit-tasks` → 升级项写成编排器任务

### Phase 4 — MCP Server（远期）
- CLI 是 ground truth，MCP 是其标准协议封装

---

## 6. 文件地图

```
context-gc/
├── SKILL.md                    # 行为契约（agent-first 主路径 + human fallback）
├── SOURCES.md                  # 本仓库自吃的权威地图（dogfood）
├── CLAUDE.md                   # 项目指令
├── README.md / README.zh-CN.md # 英文/中文说明
├── INSTALL.md                  # 安装指南
├── CONTRIBUTING.md             # 贡献者指南
├── pyproject.toml              # ruff 配置
│
├── scripts/                    # 确定性脚本（零 LLM 调用）
│   ├── _common.py              # 共享：上下文检测、autonomy 策略加载
│   ├── mark.py                 # 机械 MARK：漂移候选检测
│   ├── minor_gc.py             # 预防性 Minor GC：预授权安全修复
│   ├── review_queue.py         # 聚合待决项 → review-queue.json
│   ├── resolve.py              # Agent 自决 + 审计日志
│   ├── gc_tick.py              # 一次治理 tick（loop/agent 入口）
│   ├── init_context_gc.py      # 引导 SOURCES.md + config.yml
│   ├── context_gc_hook.py      # Hook 辅助器
│   ├── session_mark.py         # MARK 导出对话记录
│   ├── run_evals.py            # 离线 eval 检查器
│   └── validate_context_gc.py  # 结构验证器（含 dogfood 自检）
│
├── examples/                   # 9 个 demo
│   ├── demo-doc-vs-config/     # 文档 vs 配置漂移
│   ├── demo-sdd-drift/         # SDD 与实现脱节
│   ├── demo-agent-context-rot/ # Agent 上下文腐烂
│   ├── demo-agent-drift-advanced/ # 语义冲突+记忆泄漏+skill 膨胀+语调漂移+会话腐烂
│   ├── demo-minor-gc/          # 预授权安全自动修复
│   ├── demo-memory-drift/      # 记忆凝结+画像漂移
│   ├── demo-review-queue/      # 预填充待审队列
│   ├── demo-agent-autonomy/    # Agent 自主 tick：port 自修+memory 升级
│   └── demo-kb-duplication/    # 知识库重复
│
├── references/                 # 参考文档
│   ├── gc-model.md             # GC ↔ 熵 思维模型
│   ├── entropy-checklist.md    # 垃圾分类学
│   ├── treatment-playbook.md   # 按类型清理动作
│   ├── hooks.md                # Hook 方案
│   ├── mcp-surface.md          # MCP 工具接口设计
│   └── architecture.md         # 本文件
│
├── evals/evals.json            # 28 个机器可读 eval 场景
├── research/                   # 设计笔记
│   ├── context-gc-research.md  # 设计来源
│   └── loop-integration-plan.md # Loop 集成开发计划
└── templates/SOURCES.md.template # 权威地图模板
```

---

## 7. 路线图

### 下一步：Pattern Learning（自动反馈闭环）

| 任务 | 改动 | 说明 |
|---|---|---|
| `_common.py` + pattern 常量 | `_common.py` | PATTERNS_FILE 路径 |
| resolve.py 自动写 pattern | `resolve.py` | `_execute()` applied=True 后追加 patterns.jsonl |
| minor_gc.py 自动写 pattern | `minor_gc.py` | AUTO_FIXED 后追加 patterns.jsonl |
| mark.py 读取 patterns | `mark.py` | 扫描前加载 patterns，已知模式自动分类 |
| SOURCES.md.template + Pattern 字段 | `templates/` | domain 条目增加可选 Pattern 引用 |
| 新增 demo + eval | `examples/` `evals/` | pattern-learning demo + pattern 相关 eval |

### 之后：Phase 3 Loop 接缝（已设计）

- `gc_tick --gate` → loop verify_cmd
- `gc_tick --loop-state` → loop 自身 context 压缩
- `gc_tick --emit-tasks` → 升级项写成编排器 YAML 任务

### 远期：MCP Server + 团队治理面板

- MCP server 实装（CLI 是其 ground truth）
- 多仓库集中治理面板
- RBAC + Policy as Code
- 合规报告（SOX/ISO 审计）

---

## 8. 验证

```bash
python -m py_compile scripts/*.py          # 全部脚本编译通过
python scripts/validate_context_gc.py      # 结构 + dogfood 自检
python scripts/run_evals.py               # 28 eval 全部通过
python scripts/context_gc_hook.py --self-test  # hook 自检
```
