# context-gc 下一阶段设计 — 状态作用域 · 自进化闭环 · 编排接入

> 2026-06-26 · 状态：设计，未实现。先 review 架构，再分步造。
> 关联：[`loop-engineering.md`](../references/loop-engineering.md)、[`skillopt-integration.md`](skillopt-integration.md)、
> [`architecture.md`](../references/architecture.md)。

## 0. 这份文档怎么读

每条设计标注证据等级，吸取本项目自评教训（漂亮的判断要加倍怀疑）：

- **【有依据】** 有外部一手来源或项目内实测支撑。
- **【收敛假设】** 两个以上独立来源指向同一结论，可信度较高，但仍是假设。
- **【单源假设】** 只有一个来源/一次观察，听起来顺但**可能是叙事过拟合**，落地前必须再验证。

本项目血换的两条纪律，贯穿全文：
1. **不信单一自信判断**——单次 LLM 评分方差极大（soft 实测 0.0/0.2/0.8 同输入跳）。
2. **数据门控才合**——手写的"判断纪律"改动我很自信，A/B 测出 Δ=0，回滚了。

## 1. 一个根因，三个症状

这一阶段要解决的三件事，看似无关，其实是**同一个根因**：

> **`.context-gc/` 的运行时状态是全局的、无作用域的，但它记录的事实是有作用域的（属于某个 git 分支 / 某次任务 / 某个 commit）。状态和它的归属脱钩了。**

三个症状：

| 症状 | 表现 |
|---|---|
| **A. git 分支切换污染** | branch-A 的 dirty.jsonl 切到 branch-B 还在用，检查的是 B 的文件、脏卡是 A 的事实 → 误报 |
| **B. 自进化学到跨分支假 pattern** | feature 分支自决"端口该 8080"写进 patterns，被当成 main 的规律去优化 SKILL/SOURCES → 脏数据进、脏进化出 |
| **C. 跨任务经验无法安全积累** | 想让 agent 这次学的下次能用（你的"自动升级 evol"），但没有作用域就分不清"哪条经验属于哪个上下文" |

## 2. 外部设计的收敛证据

三个独立来源，对"运行时状态该怎么管"给出了**同一个答案**——这是【收敛假设】，不是单一漂亮类比：

| 来源 | 它的机制 | 映射到 context-gc |
|---|---|---|
| **LangGraph**（checkpointer + thread_id） | 状态绑 `thread_id`，不同 thread 的 checkpoint 互不污染 | `.context-gc/` 状态该绑一个 **scope id** |
| **Deep Agents v0.6 — Delta Channels** | checkpoint 不存全量快照，只存绑基线的 diff（200轮 5.27GB→129MB） | 状态记录该**绑产生它时的 git SHA**（delta 的基线） |
| **Deep Agents v0.6 — ContextHub** | agent 行为文件版本化 + 环境标签（staging/prod） + commit 历史 | SOURCES.md 状态可加**环境维度**；decisions.jsonl 已是 commit 历史的雏形 |

> 三个框架独立指向"运行时状态要绑作用域标识"。git 分支名 / commit SHA 就是 context-gc 的本地文件版 thread_id。

来源：
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [New in Deep Agents v0.6 — LangChain](https://www.langchain.com/blog/deep-agents-0-6)

## 3. 设计一：状态作用域（State Scope）

### 核心

`.context-gc/` 的每条运行时记录，绑定它产生时的**作用域标识** = `git rev-parse HEAD`（commit SHA）+ 分支名。

```
.context-gc/
├── scope.json            # 当前作用域：{branch, head_sha, recorded_at}
├── dirty.jsonl           # 每条 dirty card 带 head_sha 字段
├── patterns.jsonl        # 每条 pattern 带 branch + head_sha（学习数据的来源标注）
└── decisions.jsonl       # 已有审计，补 head_sha
```

### 分层方案（从最小可行到完整）

**① 最小可行【有依据，代码小】—— 解决 90% 痛点**
- gc_tick / hook 启动时：读 `scope.json` 的 branch vs 当前 `git rev-parse --abbrev-ref HEAD`。
- 不一致 → **dirty.jsonl 整体失效**（旧脏卡不可信），写一行提示"分支从 X 切到 Y，旧脏卡已失效，按新分支重新 MARK"。
- 理由：分支切换 = 整个工作区 ground truth 变了，是**事件**不是增量；旧增量状态不能复用。

**② 隔离【更准，更重】**
- `.context-gc/branches/<branch>/dirty.jsonl`，每分支独立，切回来能恢复。
- 代价：目录复杂化，多数用户用不上。**非默认。**

**③ SHA 绑定【最准，CI 级】**
- 每条记录带 head_sha，检查时逐条对比，只失效 SHA 不匹配的。
- 适合严格/CI 场景。**非默认。**

**默认选 ①。** patterns.jsonl / decisions.jsonl 这类"学习数据"无论选哪层，都**必须带 branch + head_sha 来源标注**——否则设计二的自进化会被污染。

### 非目标
- 不接管 git 操作，不替用户切分支。只**观察** HEAD，只让自己的状态对齐。

## 4. 设计二：自进化闭环（Evol Loop）

### 目标（你的原话）

> agent 自主调用 context-gc 后，系统自动升级优化 evol 里的东西。

让 eval 集从"我们手写的 37 个"变成**从真实使用中生长**——这直接解决最早那个担心："eval 都是我们自己定义的"。

### 闭环全貌

```
agent 自主调用 gc_tick（设计三的接入点触发）
        │
        ▼
真实漂移 → 写 patterns.jsonl（带 scope 来源标注，设计一）
        │
        ▼
analyze_patterns.py 聚类 → 发现"同类漂移反复出现 N 次"
        │
        ├─❶ 升级 SOURCES.md 契约         【已有：--apply】
        └─❷ 生成候选新 eval → evals.json  【缺这一环，本设计的核心】
        │
        ▼  ★★★ 防噪声门控（不可省）★★★
候选 eval 只有满足以下全部才进集合：
   (a) 同一漂移模式在 ≥2 个不同 scope（分支/任务）出现 → 不是单分支偶然
   (b) samples≥3 共识下，当前 SKILL.md 在这个候选 eval 上稳定失败
       （hard 多数票=0）→ 它暴露了真实弱点，不是噪声
   (c) 人审一次（环境标签 staging）→ 借鉴 ContextHub 的 staging→prod
        │
        ▼
新 eval 进集合（标 source=evol, scope=...）
        │
        ▼
下次 skillopt_optimize 用它优化 SKILL.md（门控：valid 集严格提升才合）
        │
        ▼
SKILL 变强 → agent 自主调用更准 → 回到顶部
```

### 为什么门控是死命令【有依据——本会话实测】

没有门控，自进化会变成**噪声放大器**。本会话三个实测证据：
1. 单次评分 soft 在 0.0/0.2/0.8 跳 → 单次判断"这是好 eval"不可信。
2. 我自信的 SKILL 改动，A/B 测 Δ=0 → 自信 ≠ 正确。
3. SkillOpt optimizer 两次提的编辑被门控拒 → 自动生成的东西经常该被拒。

**结论：自动生成候选可以，自动合并绝不可以。** 每一环都要 samples 共识 + 门控 + 至少一次人审（staging）。这不是保守，是本会话用数据换来的。

### 与设计一的依赖

❷ 聚类依赖 patterns.jsonl 的 scope 标注。**没有设计一，设计二学到的是跨分支假 pattern。** 必须设计一先落地。

## 5. 设计三：编排框架接入（Orchestrator Adapters）

### 原则【有依据】

context-gc 是 **sidecar**：零依赖、CLI、通吃所有 agent。**学编排框架的设计，不进它们的笼子。** 建在 LangGraph / Deep Agents 上 = 放弃"适配所有智能体"硬需求，且正面撞 LangSmith 商业产品，必死。

### 接入矩阵

| 框架 | 接入点 | 模式 | 状态 |
|---|---|---|---|
| **Hermes / Ralph** | `hermes_adapter.py gate/emit-tasks/compact` | verify_cmd | ✅ 已有 |
| **LangGraph** | context-gc 作为图里一个 **verification node** | node 内调 gc_tick，escalated>0 → `interrupt()` 升级人审 | 【收敛假设】待造 |
| **Deep Agents** | 挂成一个 middleware / 在 ContextHub commit 前跑 gate | pre-commit 检测层 | 【单源假设】待验证 |
| **任意 CLI agent** | `gc_tick --quiet` | 项目规则里一行 | ✅ 已有 |

### LangGraph 接入的同构【收敛假设】

LangGraph 的 `interrupt() + conditional edge`（commit 前人工审批，验证不过 loop 回去）和 context-gc 的 `gc_tick --gate + review_queue 升级` 是**同一个模式**。所以 context-gc 能当 LangGraph 图里的验证节点：

```
agent node → context-gc verify node → conditional edge
                  │                        ├─ clean → 继续
                  └─ gc_tick               └─ escalated>0 → interrupt() 人审
```

来源：[LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

### ContextHub 的竞争判断【单源假设——必须再验证】

> ⚠️ 这个判断对我们有利，按自评纪律加倍怀疑。只有一个信源（ContextHub 官方描述不含漂移检测）。

- ContextHub 做的是**存储 + 版本化**（给 agent 记忆装了 Git）。
- 它官方描述里**没有**"检测两份记忆矛盾 / 文档与代码漂移"。
- context-gc 做的是**检测 + 治理**（agent 记忆的 GC + pre-commit lint）。
- **假设**：版本化越普及，"提交前内容是否一致"的需求越突出，而那正是 context-gc。就像 Git 普及后才有 pre-commit hook。
- **验证方法**（落地前必做）：找 3 个真实案例——有人用 ContextHub/AGENTS.md 存了 agent 记忆，然后吃了"存进去的东西自相矛盾"的亏。找到 → 假设成立、可定位；找不到 → 老实做检测工具，不碰这套叙事。

## 6. 跨模型共识评分【收敛假设】—— Harness Profiles 的启发

Deep Agents 的 Harness Profiles 说：同一份 skill，不同模型读它表现差很多，要 per-model 调优（实测同模型只调 harness +13.7 分）。

映射：一个真正"适配所有智能体"的 SKILL.md，该在 **Claude / DeepSeek / GLM 上都拿高分**，而不只是 DeepSeek。

- 现状：`eval_for_skillopt --samples 3` 是**单模型多次**共识。
- 升级：**多模型各评 → 取跨模型共识**。一个模型给高分可能是过拟合那个模型，多模型都给高分才是真通用。
- 代价：多倍 API + 多个 key。**非默认，按需开。**

来源：[New in Deep Agents v0.6](https://www.langchain.com/blog/deep-agents-0-6)

## 7. 分步实现顺序（依赖决定）

```
✅ 第1步【设计一·最小可行】  scope.json + 分支切换失效 dirty
   └─ _common.py: is_git_repo/current_scope/scope_changed/write_scope
   └─ gc_tick: mark 前检测分支切换，失效旧脏卡，记录新 scope；非 git 跳过。eval #38。
✅ 第2步【设计一·学习数据标注】 patterns/decisions 带 scope
   └─ resolve.py: decisions 记 scope；_record_pattern 把成功自决写 patterns.jsonl（带 scope）
   └─ analyze_patterns: _scope_count — 跨多分支重复是更强证据
✅ 第3步【设计二·候选生成】  analyze_patterns --emit-eval（只生成候选，不合）
   └─ 候选写 candidate-evals.json，带门控元数据（cross_scope_ok / needs_consensus_check /
      needs_human_review）。**绝不进 evals.json。**
✅ 第4步【设计三·LangGraph 节点】 langgraph_adapter.py（不引 langgraph 依赖）
   └─ template 印可粘贴节点；gate 跑一次 tick 出 decision（clean/escalate/error）驱动条件边。
⬜ 第5步【设计二·全闭环】  候选→人审 staging→优化→门控合
   └─ 依赖第3步 + skillopt_optimize（已有）。把 candidate-evals 经 (b) samples 共识 +
      (c) 人审后，合进 evals.json，再触发 skillopt 优化 SKILL。这是闭环的最后一环。
```

每步都：samples 共识验证 + 数据门控 + dogfood 绿。前 4 步已落地（见上方 ✅），第 5 步是闭环收口。

## 8. 守住的边界（不可动摇）

1. **sidecar 定位**：零依赖、CLI、通吃所有 agent。学设计，不进笼子。
2. **检测/治理层，不做存储层**：存储 + 版本化是 ContextHub/LangSmith 的生意，正面撞必死。我们做它们没做的——漂移检测、内容一致性、来源完整性。
3. **自动生成可以，自动合并不行**：每个进化环节 samples 共识 + 门控 + staging 人审。
4. **never_auto 代码地板不变**：protected / delete / memory-condense / unknown-root 永远升级给人。
