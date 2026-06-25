# context-gc

[English](README.md) | [中文](README.zh-CN.md)

> 文档与 Agent 上下文的垃圾回收——检测漂移、过时、矛盾、重复和上下文腐烂；追溯每条事实到权威来源；收敛或清除垃圾后留下 `SOURCES.md`，让未来的漂移尽早被发现。

```
┌───────────┐    ┌───────────┐    ┌───────────┐
│  MARK     │ →  │  SWEEP    │ →  │  BARRIER  │
│ (诊断)    │    │ (治理)    │    │ (预防)    │
│           │    │→ 确认后   │    │           │
│ 只读      │    │  再写入   │    │SOURCES.md │
└───────────┘    └───────────┘    └───────────┘
```

## 快速开始

1. **安装**：[`install.py`](install.py) 一条命令搞定：

   ```bash
   curl -sSL https://raw.githubusercontent.com/matata2017/context-gc/main/install.py | python3
   ```

   或者把 [这段话](INSTALL_AGENT.md) 发给你的 agent——它自己会装。完整选项：[`INSTALL.md`](INSTALL.md)
2. **阅读 skill**：[`SKILL.md`](SKILL.md)
3. **试试 demo**：
   - [`examples/demo-doc-vs-config/`](examples/demo-doc-vs-config/) — README 写端口 8000，compose 实际是 8080
   - [`examples/demo-sdd-drift/`](examples/demo-sdd-drift/) — SDD 写密码登录，代码/测试用 OAuth 设备流
   - [`examples/demo-agent-context-rot/`](examples/demo-agent-context-rot/) — SOUL 引用已删除的 skill 且有冲突的速率限制
   - [`examples/demo-agent-autonomy/`](examples/demo-agent-autonomy/) — agent 自动修端口 mismatch，memory 冲突升级给人
   - [`examples/demo-kb-duplication/`](examples/demo-kb-duplication/) — 同样的部署指令复制在 README/docs/wiki 三处
4. **跑结构验证**：
   ```bash
   python scripts/validate_context_gc.py
   ```
5. **跑离线 eval**：
   ```bash
   python scripts/run_evals.py
   ```
6. **可选：安装 hooks**，用 [`examples/claude-settings-hooks.json`](examples/claude-settings-hooks.json)。hooks 会在 `.context-gc/dirty.jsonl` 中记录脏文件、提醒你跑 MARK，还可以阻止未经批准的批量清理。

## 解决的问题

文档、配置、知识库和 AI agent 指令会腐烂：
- 代码变了，文档没变
- 同一个事实复制到五个地方，各自漂移
- 本地配置和生产环境分道扬镳
- 状态文件写完那一刻就过时了
- Agent 上下文（SOUL/CLAUDE.md/memory）积累死掉的、矛盾的垃圾 → **上下文腐烂**
- 知识库膨胀到没人知道哪行是真的

## 解决思路：当垃圾回收来治

这个比喻在结构上是精确的，不是修辞——GC 概念 1:1 映射：

| GC 概念 | 上下文熵 |
|---|---|
| 根（Root） | 某个事实的权威来源（代码/配置/CLAUDE.md） |
| 存活/可达（Live） | 能追溯到根且仍匹配根的陈述 |
| 垃圾（Garbage） | 过时、孤立、矛盾、重复的内容 |
| 标记（Mark） | 找根 → 追溯每条声明 → 标记垃圾（只读） |
| 清除（Sweep） | 调和/删除/压缩垃圾（确认后才写） |
| 压缩（Compaction） | 去重到一个权威源；裁剪 agent 上下文 |
| 写屏障（Write barrier） | `SOURCES.md`——权威地图，下次轻量重检 |

完整研究笔记与设计理由：[`research/context-gc-research.md`](research/context-gc-research.md)。

## 覆盖范围

- **文档和 README** — 过时、矛盾、孤立的声明
- **SDD 和规格** — 需求变更后规格文字与代码脱节
- **配置** — 本地↔服务器漂移、被掩盖的配置、注明的 fork 差异
- **知识库** — 膨胀、重复、不断追加式腐烂
- **Agent 上下文** — SOUL/CLAUDE.md/skills/memory 上下文腐烂（过时指令、语义冲突、死引用、内存泄漏、skill 膨胀、语调漂移）
- **Agent 记忆层** — 长期、中期和画像记忆冲突或漂移；`memory-condense` 写入一份当前记忆并保留原件作为证据
- **单次会话** — 对话记录/会话腐烂：被取代的计划、孤立的 TODO、重复的决策和工具输出膨胀
- **预防性 Minor GC** — 自动化 agent 可周期性检查脏上下文，仅应用预先授权的安全修复，在漂移扩散前拦截

## 用法（作为 Claude Code skill）

将此目录安装为 Claude skill（或复制到你的 Claude skills 目录）。skill 在遇到以下情况时触发：文档过时、配置漂移、来源矛盾、知识库膨胀或 agent 上下文腐烂。

常见的触发语句：
- "文档过时了 / 对不上了"
- "配置漂移了" / "这两个互相矛盾"
- "清理下文档" / "给知识库做个 GC"
- "我的 agent 感觉比以前笨了" / "上下文腐烂了"
- "治理下文档漂移"

Claude 会执行 **三阶段 GC 循环**：
1. **MARK** — 划定堆范围，找到根，追溯每条声明，输出熵报告
2. **SWEEP** — 提出清理计划等待确认，确认后执行治理
3. **BARRIER** — 写入/更新 `SOURCES.md`（权威地图，下次跑更轻量）

可选的 hook 集成能让它变成增量 GC：`PostToolUse` 记录脏上下文文件，`Stop` 在熵积累前提醒你跑 MARK，可选的 `PreToolUse` 拦截未经批准的批量清理。详见 [`references/hooks.md`](references/hooks.md) 和 [`examples/claude-settings-hooks.json`](examples/claude-settings-hooks.json)。

## Agent-first 模式

context-gc 为 agent-first 世界设计：**loop / agent 驱动它**，自动消解被允许的漂移，只把策略保留给人的部分升级出去。人设定策略一次，审计留痕——不需要每次都操作工具。

```bash
python scripts/gc_tick.py --target .          # 跑一次治理 tick，打印结构化 TickResult JSON
python scripts/gc_tick.py --target . --quiet  # 只打印一行摘要
```

`gc_tick` 链条：`mark → minor_gc → review_queue → resolve --auto`。永不阻塞。待决升级项累积在队列中；agent 自决写入 `.context-gc/decisions.jsonl` 并附证据和可回滚标记。

自治策略在 `.context-gc/config.yml` 的 `autonomy:` 块中配置，level 从 `off`（全不自动）到 `full`（全自动除 `never_auto` 红线）。`never_auto` 是代码级硬地板——即使 `level: full` 也不会自决 protected 文件、删除操作、memory 写入或模糊项。

## 为什么不直接用文档 linter？

用它们。`context-gc` 不是 Vale、markdownlint、lychee 或项目专属检查的替代品。那些工具是扫描器：它们在 MARK 阶段产出证据。`context-gc` 是包裹它们之上的收集器协议：找根、追溯声明、确认 SWEEP、然后把根→副本关系记录在 `SOURCES.md` 里，让同样的漂移下次检测成本更低。

完整 skill 行为契约：[`SKILL.md`](SKILL.md)

## 文件结构

```
context-gc/
├── .editorconfig                    # 跨平台文本编码和 LF 换行
├── .github/workflows/validate.yml   # GitHub Actions 验证
├── SKILL.md                         # 完整 skill — GC 循环、安全规则、输出格式
├── SOURCES.md                       # 本仓库自吃的权威地图
├── README.md                        # 英文版（本文件）
├── README.zh-CN.md                  # 中文版
├── INSTALL.md                       # 安装、hook、CI 快速指南
├── CONTRIBUTING.md                  # 贡献者工作流和验证命令
├── evals/
│   └── evals.json                   # 机器可读的 eval 场景
├── research/
│   ├── context-gc-research.md       # 设计来源与建议
│   └── loop-integration-plan.md     # Loop 集成开发计划
├── references/
│   ├── gc-model.md                  # GC ↔ 熵 思维模型
│   ├── entropy-checklist.md         # 垃圾分类 + 检测方法
│   ├── treatment-playbook.md        # 按类型的清理动作
│   ├── mcp-surface.md               # MCP 工具接口设计（server 远期）
│   └── hooks.md                     # 可选的 Claude Code hook 方案
├── scripts/
│   ├── _common.py                   # 共享的上下文路径、预算和自治策略辅助
│   ├── context_gc_hook.py           # Hook 辅助：脏卡、拦截、提醒、静默 auto-MARK
│   ├── init_context_gc.py           # 引导 SOURCES.md + 可选的堆画像
│   ├── mark.py                      # 机械 MARK：文档/配置/agent 漂移候选
│   ├── minor_gc.py                  # 预防性 Minor GC（仅预授权安全修复）
│   ├── review_queue.py              # 聚合待决决策 → review-queue.json
│   ├── resolve.py                   # Agent 自决（自治策略内）+ 审计日志
│   ├── gc_tick.py                   # 一次治理 tick，任何 loop/agent 可调用
│   ├── session_mark.py              # MARK 导出的对话记录
│   ├── run_evals.py                 # 离线 eval 夹具检查器
│   └── validate_context_gc.py       # 结构验证器
├── examples/
│   ├── claude-settings-hooks.json   # 示例 .claude/settings.json hook 配置
│   ├── demo-doc-vs-config/         # 过时 README vs 实际 docker-compose 端口
│   ├── demo-sdd-drift/             # SDD 与实现脱节
│   ├── demo-agent-context-rot/     # 死 skill + 冲突的 agent 指令
│   ├── demo-agent-drift-advanced/  # 语义冲突、内存泄漏、skill 膨胀、会话腐烂
│   ├── demo-minor-gc/              # 预授权 scalar-sync 安全自动修复
│   ├── demo-memory-drift/          # 长期/中期记忆凝结 + 画像漂移
│   ├── demo-review-queue/          # 预填充的待审队列夹具
│   ├── demo-agent-autonomy/        # Agent 自主 tick：端口自修 + memory 升级
│   └── demo-kb-duplication/        # 同样的事实复制在 README/docs/wiki
└── templates/
    └── SOURCES.md.template          # 权威地图模板（写屏障）
```

## 开发

```bash
python scripts/validate_context_gc.py
python scripts/run_evals.py
```

本仓库在 [`SOURCES.md`](SOURCES.md) 中自吃自己的写屏障。改动 skill、hook、demo 或 GitHub 元数据时，如果根→副本关系变了，记得更新对应的权威地图条目。

## License

MIT — fork，remix，dogfood，contribute。

## 参考资料

- [LogRocket: Context rot is slowing down your AI agent](https://blog.logrocket.com/context-rot-slowing-down-your-ai-agent-how-fix/)
- [MindStudio: What is context rot and how do you prevent it?](https://www.mindstudio.ai/blog/what-is-context-rot-ai-agents)
- [Josys: Configuration drift lifecycle](https://josys.com/article/understanding-the-lifecycle-of-configuration-drift-detection-remediation-and-prevention)
- [Computhink: SSoT in document governance](https://computhink.com/blog/why-a-single-source-of-truth-is-critical-for-enterprise-document-governance/)
