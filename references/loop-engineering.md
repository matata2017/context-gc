# context-gc × Loop Engineering

> 基于 LangChain《The Art of Loop Engineering》(2026.06) 的四层架构，逐层拆解 context-gc 的位置、已实现和未实现。

Boris Cherny (Claude Code 负责人): "我的角色从每次手动提问变成了设计一个能一直问下去的循环。"

context-gc 在回答同一个问题的子集：**agent 干活过程中漂移了，谁来发现、谁来修、谁来保证下次不会犯同样的错？**

---

## 四层全景图

```
┌──────────────────────────────────────────────────────────────┐
│ L4 · 爬坡循环（Hill Climbing）                                │
│ patterns.jsonl → analyze_patterns.py → 自动更新检测规则        │
│ "让 AI 替你优化它自己的工作方式"                              │
├──────────────────────────────────────────────────────────────┤
│ L3 · 事件驱动循环（Event-driven）                              │
│ hook dirty-card → auto-MARK → gc_tick → 等待下次事件           │
│ "7×24 小时持续运转，不等人来触发"                              │
├──────────────────────────────────────────────────────────────┤
│ L2 · 验证循环（Verification）                                  │
│ gc_tick --gate: mark → minor_gc → resolve                     │
│ "agent 输出通过质检才能算完成"                                 │
├──────────────────────────────────────────────────────────────┤
│ L1 · 智能体循环（Agent Loop）                                  │
│ 用户的 agent 写代码、改文档、调工具...                          │
│ context-gc 不参与这一层（我们是 Sidecar）                      │
└──────────────────────────────────────────────────────────────┘
```

---

## L2 — 验证循环（Verification Loop）⚡ 80% 完成

### 做什么

agent 完成一个任务后，验证它是否引入了上下文漂移。不合格 → 自动修复或升级。

### context-gc 的实现

```
用户的 agent 完成任务
      │
      ▼
┌─────────────┐
│  gc_tick     │  ← 这就是 verify_cmd
│  --gate      │
└──────┬──────┘
       │
       ├─ 1. mark.py      确定性规则校验（端口不对、引用死了、指令冲突...）
       │     status: ✅
       │
       ├─ 2. minor_gc.py  预授权安全修复（scalar-sync、pointer-copy）
       │     auto_fixed: N    status: ✅
       │
       ├─ 3. review_queue  聚合待决项
       │     status: ✅
       │
       └─ 4. resolve.py   策略内自决 / 策略外升级
             ┌─ agent_resolved: N  → 无问题
             └─ escalated: N      → exit 1 → loop 标 verify_failed
```

### 对应关系

| LangChain 原文 | context-gc |
|---|---|
| 确定性规则校验：链接有效性、CI、代码格式 | `mark.py` 的 7 种检测器（stale/contradiction/orphan/duplicate/memory-conflict/tone-drift 等） |
| LLM 裁判校验：内容完整性、受众适配度 | `review_queue` + SKILL review（AskUserQuestion）——人/LLM 裁决模糊项 |
| 校验失败 → 带反馈重试 | `escalated > 0` → exit 1 → loop 重新解决 → 再次 gate |
| 校验通过 → 结束流程 | `escalated=0 && pending=0` → exit 0 |

### 缺口

| 缺什么 | 怎么做 |
|---|---|
| ❌ LLM 裁判在 agent 路径里 | 现在只有人的 SKILL review。agent 自决路径需要让 agent 自己调 LLM 判断模糊项——但这属于调用方 agent 的事，context-gc 不替它调 |
| ❌ 重试闭环 | `gc_tick --gate` exit 1 后，需要 loop engine 自动重新解决 + 重新验证。现在是 loop engine 的职责，我们提供了 exit code |

---

## L3 — 事件驱动循环（Event-driven Loop）⚡ 40% 完成

### 做什么

不靠人手动触发。文件变更 = 事件 = 自动跑验证。

### context-gc 的实现

```
文件被编辑（Write/Edit）
      │
      ▼
┌──────────────────┐
│ PostToolUse hook  │  → 写 dirty.jsonl
│ dirty-card        │
└──────┬───────────┘
       │ 脏卡数 ≥ threshold（比如 10）
       ▼
┌──────────────────┐
│ auto-MARK         │  → mark.py --dirty-only
│ (hook 内触发)      │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ minor_gc（可选）   │  → 消得掉的自动修
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Stop hook         │  → "N 个漂移决策等你"
│ 提醒              │
└──────────────────┘
```

### 对应关系

| LangChain 原文 | context-gc |
|---|---|
| 外部事件触发 | PostToolUse hook：Write/Edit 事件 |
| 启动校验循环 | dirty-card 达到阈值 → auto-MARK |
| 完成后同步更新业务系统 | `gc_tick` 写入 tick.json + patterns.jsonl + decisions.jsonl |
| 等待下一轮事件 | 下一个 Write/Edit → 下一个 dirty-card |

### 缺口

| 缺什么 | 怎么做 |
|---|---|
| ❌ 跨会话持久 | dirty.jsonl 在会话间持久（已实现），但没有跨仓库的事件流 |
| ❌ 独立运行 | 目前依赖 Claude Code hook 机制。如果用户用的是其他 agent 平台，事件流需要自己实现 |
| ❌ 业务事件集成 | 不能接 GitHub webhook / Slack / Jira。做不做取决于是否要"企业版" |

**L3 的最小补齐：** 让 `gc_tick` 可以被 cron / GitHub Actions / loop interval 驱动，不依赖 Claude Code hook。这一点已实现——`gc_tick.py` 本身不依赖 hook。

---

## L4 — 爬坡循环（Hill Climbing Loop）⚡ 设计完成，未实现

### 做什么

前三层是"让 AI 替你工作"，第四层是 **"让 AI 替你优化它自己的工作方式"**。

全链路日志 = patterns.jsonl + decisions.jsonl + findings.json。
分析智能体扫描日志 → 发现系统性缺陷 → 自动更新检测规则。

### context-gc 的实现（设计）

```
patterns.jsonl           decisions.jsonl         findings.json
(历史成功的模式)          (每次自决记录)           (检测结果)
      │                       │                      │
      └───────────────────────┼──────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  analyze_patterns.py          │
              │  (爬坡分析智能体)              │
              │                               │
              │  1. 按 kind+domain 聚类 pattern│
              │  2. 统计同类出现频率           │
              │  3. 同一模式 ≥ 3 次 → 建议升级  │
              │  4. 生成优化方案               │
              └───────────────┬───────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  optimization-proposals.json  │
              │                               │
              │  - "port mismatch 出现了 5 次" │
              │    → 建议：SOURCES.md 加       │
              │    scalar-sync 契约            │
              │                               │
              │  - "concise vs verbose 冲突    │
              │    出现了 3 次"                │
              │    → 建议：memory domain       │
              │    加 Pattern 字段             │
              └───────────────┬───────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  人工审核（Human-in-the-loop）  │
              │  ✓ 批准 → 更新 SOURCES.md       │
              │  ✗ 拒绝 → 记录跳过              │
              └───────────────────────────────┘
```

### 对应关系

| LangChain 原文（LangSmith Engine） | context-gc |
|---|---|
| 全流程运行轨迹日志 | patterns.jsonl + decisions.jsonl + findings.json |
| 分析智能体扫描日志 | `analyze_patterns.py`（爬坡分析） |
| 识别系统性缺陷 | 按 kind+domain 聚类，统计复发次数 |
| 自动生成优化工单 | `optimization-proposals.json` |
| 自动更新提示词/工具/校验规则 | 更新 SOURCES.md 契约 + Pattern 字段 |
| 人工审核后上线 | git diff → 人确认 → merge |

### 待实现

| 任务 | 说明 |
|---|---|
| `scripts/analyze_patterns.py` | 读取 patterns.jsonl，按 kind+domain 聚类，统计复发频率 |
| `optimization-proposals.json` 格式 | 标准化输出：建议类型 + 证据 + 推荐操作 |
| 自动更新 SOURCES.md | 从建议自动生成 SOURCES.md 条目（人确认后 apply） |
| eval 覆盖 | 爬坡分析正确聚类的 eval |

---

## 人机协同

四层循环都预留了人工介入点，对应文章里的 Human-in-the-loop 设计：

| 层级 | 人工介入点 | context-gc 实现 |
|---|---|---|
| L1 Agent Loop | 高风险工具调用前人工审批 | 不在 context-gc 范围内（用户的 agent 自己控制） |
| L2 Verification | 复杂/模糊项由人裁决 | `never_auto floor` —— protected/delete/memory/unknown-root 永远升级给人 |
| L3 Event-driven | 交付物人工确认后再同步 | review-queue 积累 → Stop hook 提醒 → `/context-gc review` |
| L4 Hill Climbing | 自动生成的规则更改人工审核后上线 | `optimization-proposals.json` → git diff → 人 approve → merge |

**机器负责：** 标准化扫描、重复性修复、大批量检测、pattern 聚类
**人负责：** 价值判断（FORK vs HISTORICAL）、行业专业审美（SDD 未来意图 vs 当前事实）、高风险决策（删除、记忆重写）

---

## 竞争壁垒

文章指出 "单纯依赖模型、堆砌提示词的智能体极易被复刻"。context-gc 从第一天就在执行这个判断：

| 可复刻的东西 | 不可复刻的东西 |
|---|---|
| 2000 行 Python 脚本 | 28 个 eval 覆盖的漂移分类知识 |
| mark.py 的检测函数 | 每个真实项目积累的 patterns.jsonl |
| SOURCES.md 格式 | 团队在所有仓库建立的一致性契约网络 |
| 安装命令 | 部署后运行一个月积累的 decisions.jsonl 审计链 |

**真正的护城河不是代码，是 Loop 跑出来的数据。**

---

## 开发优先级

1. **立即实现：** `analyze_patterns.py`（爬坡分析）→ Layer 4 落地
2. **随后：** `gc_tick --gate` / `--loop-state` / `--emit-tasks` → Layer 2-3 的 loop engine 接缝
3. **远期：** MCP server + 团队治理面板 → 四层循环的集中管理
