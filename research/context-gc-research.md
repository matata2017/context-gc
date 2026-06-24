# context-gc 深研报告：文档漂移、文档熵增与 Agent Context Rot 的系统治理

> 生成时间：2026-06-24  
> 来源：deep-research 工作流已完成的 Search/Fetch/部分 Verify 结果；原完整 Verify 阶段因 25 claims × 3 voters 过重被中止，后续以已抓取的一手/二手来源手工综合。

## 1. 核心结论

`context-gc` 的 GC 模型是合理的，而且比普通“文档清理”更贴近工程实践。

业界已有成熟类比：

- 配置漂移治理使用 **expected vs actual**、**desired state vs live state**、**drift status**、**reconcile** 等模型；这与 `context-gc` 的 root/live/garbage/mark/sweep 完全同构。
- Docs-as-code 把文档纳入 Git、review、CI、lint、ownership，与代码一起演进，本质是在给文档建立 **root set + write barrier**。
- AI agent context rot 的治理正在走向 **context editing / memory externalization / pruning / summarization / tool loadout**，这和 GC 的 sweep/compaction/offloading 高度一致。

因此 `context-gc` 应定位为：

> Garbage collection discipline for docs, configs, knowledge bases, and AI-agent context — not a one-time doc cleanup tool.

## 2. 定义与风险

### 2.1 文档漂移 / doc rot / KB decay

文档漂移指文档中的事实与当前真实系统、配置、代码、流程或决策不一致。典型成因：

- 代码或配置变了，README/wiki 没跟上。
- 同一事实复制到多处，后续只改了其中一处。
- 历史计划、状态文件、会议纪要不断累积，却没有收敛到当前事实。
- 文档缺少 owner 与 review gate。

Docs-as-code 社区将文档治理纳入开发流程：使用 issue tracker、Git、plain text markup、code review、automated tests，并主张文档与开发团队同流程协作。Write the Docs 明确说 docs-as-code 是用与代码相同的工具写文档，并可通过“新功能没有文档就阻止合并”来减少漂移。[Write the Docs — Docs as Code](https://www.writethedocs.org/guide/docs-as-code/)

GitLab 更明确把官方文档定义为配置、使用和排障 GitLab 的 **single source of truth**，并用 MR、Bot、Technical Writer owner、Vale、markdownlint、link checks 等治理文档质量。[GitLab Documentation](https://docs.gitlab.com/development/documentation/) [GitLab Documentation testing](https://docs.gitlab.com/development/documentation/testing/)

### 2.2 配置漂移 configuration drift

配置漂移是最成熟的参考对象。

AWS CloudFormation 将 drift 定义为 stack 的 actual configuration 与 template/parameters 定义的 expected configuration 不一致；只要一个资源漂移，整个 stack 就可被视为 drifted。CloudFormation 还把漂移状态区分为 DRIFTED、IN_SYNC、NOT_CHECKED，并明确检测边界：只检测支持 drift detection 的资源，只检测模板/参数显式设置的属性，父栈不会自动检测 nested stacks。[AWS CloudFormation Drift Detection](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-stack-drift.html)

Terraform 官方教程则把漂移描述为 Terraform 管理的资源被工作流外手工修改，导致 state file 与真实基础设施不同步。`-refresh-only` 被推荐为更安全的漂移检测/状态同步方式，因为它不会直接修改基础设施；这给 `context-gc` 一个重要边界：**先检测/标记，再决定是否修复**。[HashiCorp Terraform Drift](https://developer.hashicorp.com/terraform/tutorials/state/resource-drift)

Argo CD 的自动同步说明了 GitOps 的持续 reconcile 模型：当 Git 中 desired manifests 与 Kubernetes live state 不一致时可自动同步；但删除资源需要显式启用 prune，live cluster 手改要 selfHeal，空资源 prune 有 allowEmpty 保护。这说明 sweep 中的破坏性操作应有显式开关。[Argo CD Automated Sync](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)

OpenGitOps 四原则则进一步抽象：desired state 必须声明式表达，存储在具备版本化和完整历史的介质中，agent 自动拉取 desired state，并持续观察 actual state、尝试应用 desired state。[OpenGitOps Principles](https://opengitops.dev/)

### 2.3 AI Agent Context Rot

Agent context rot 指长期会话、记忆、工具定义、旧指令、错误摘要、死上下文和冲突信息不断堆积，导致模型质量下降。

Chroma 的 Context Rot 技术报告测试 18 个长上下文模型，结论是输入 token 增加会导致性能下降，且下降模式非平滑、非一致；即使相关信息在上下文中，信息如何呈现也很重要。[Chroma Context Rot](https://www.trychroma.com/research/context-rot)

Drew Breunig 将长上下文失败分成四类：

- context poisoning：错误/幻觉进入上下文后反复被引用。
- context distraction：上下文太长导致模型过度依赖历史而不是训练知识。
- context confusion：无关信息或工具让模型输出质量下降。
- context clash：上下文内部信息冲突。

这些正好对应 `context-gc` 的 garbage taxonomy：污染、分心、混淆、冲突。[How Long Contexts Fail](https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html)

其后续文章给出治理方法：RAG、tool loadout、context quarantine、context pruning、context summarization、context offloading，并强调“context is not free”。这对应 GC 的 selective loading、mark/sweep、generation isolation、compaction、external memory。[How to Fix Your Context](https://www.dbreunig.com/2025/06/26/how-to-fix-your-context.html)

Anthropic 官方 context management 文章也直接支持该方向：context editing 会在接近 token limit 时自动清除 stale tool calls/results；memory tool 将知识存放到 context window 外。文中报告 context editing 在 100-turn web search 测试中减少 84% token，context editing 单独提升 29%，memory + context editing 提升 39%。[Claude context management](https://claude.com/blog/context-management)

Manus 的 agent context 工程文章提出：保持 prompt prefix stable、文件系统作为外部记忆、todo.md 把目标移到上下文尾部、不要删除失败证据。这说明 agent context GC 不能粗暴“清空历史”，而应区分可删垃圾、需压缩证据、需外部化记忆。[Manus Context Engineering](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)

## 3. 常用治理方法

### 3.1 Single Source of Truth / Root Set

文档漂移的核心是没有权威源。GitLab 把官方文档定义为 SSoT；OpenGitOps 把 Git 里的 desired state 作为声明式权威；CloudFormation/Terraform 把 template/config/state 作为期望状态或管理记录。

`context-gc` 的 `SOURCES.md` 应明确充当 root set：每个 fact domain 一个 root，派生副本必须指向 root，而不是重复权威陈述。

### 3.2 Docs-as-code + Review Gates

Docs-as-code 的关键不是“Markdown 放 Git 里”，而是把文档纳入代码同等流程：MR、review、CI、owner、测试。Write the Docs 明确列出 issue tracker、Git、plain text markup、code review、automated tests。[Write the Docs — Docs as Code](https://www.writethedocs.org/guide/docs-as-code/)

GitLab 实践更完整：

- Markdown 变更触发 CI。
- Vale 检查 prose/content。
- markdownlint 检查结构。
- link jobs 检查相对链接、锚点和源码到文档链接。
- redirect checks 防 rename/delete 后链接腐烂。
- front matter ownership 是测试对象。
- Vale/markdownlint config 在 `gitlab` 项目中作为 source of truth，再同步出去。[GitLab Documentation testing](https://docs.gitlab.com/development/documentation/testing/)

### 3.3 文档质量工具生态

- **Vale**：把编辑风格指南自动化，支持自定义规则、离线运行、VS Code/GitHub Actions 集成；适合术语一致性、禁用词、语气、风格规则。[Vale](https://vale.sh/)
- **markdownlint**：Markdown/CommonMark 静态分析，检查标题层级、列表、空行、代码块等结构一致性，可接入 CLI/pre-commit/GitHub Actions。[markdownlint](https://github.com/DavidAnson/markdownlint)
- **lychee**：快速链接检查器，支持 Markdown/HTML/网站/文件 glob，提供 GitHub Action、pre-commit、JSON/JUnit/Markdown 输出，适合 link rot。[lychee](https://github.com/lycheeverse/lychee)
- **Backstage TechDocs**：docs-like-code，工程师把 Markdown 文档与代码同仓，通过 CI/CD 生成发布，服务页发现文档，支持反馈闭环与未来 trust score/maintenance notifications。[Backstage TechDocs](https://backstage.io/docs/features/techdocs/)
- **Diátaxis**：把技术文档分成 tutorials、how-to guides、reference、explanation，用用户需求组织文档，减少知识库结构混乱。[Diátaxis](https://diataxis.fr/)
- **ADR**：记录单个架构决策及其 rationale、trade-offs、consequences，项目 ADR 集合构成 decision log，可作为“为什么这样”的权威根。[ADR GitHub](https://adr.github.io/)

## 4. GC 模型映射是否合理

合理，而且有工程对应物：

| GC 概念 | 文档/配置/Agent 映射 | 参考实践 |
|---|---|---|
| root | 权威源：代码、IaC、live config、ADR、CLAUDE.md/SOUL、canonical docs | GitLab SSoT, OpenGitOps desired state |
| live | 能追溯到 root 且仍正确的事实 | CloudFormation expected vs actual |
| garbage | 陈旧、矛盾、重复、孤儿、污染、无关上下文 | doc rot, context poisoning/clash |
| mark | 诊断：读取 roots，追踪 claims，标记 drift | Terraform refresh-only, CloudFormation detect drift |
| sweep | 治疗：更新、删除、压实、重定向 | Argo sync/prune，但 destructive 操作要开关 |
| compaction | 去重、摘要、外部化、保留指针 | context summarization/offloading, TechDocs centralized portal |
| write barrier | hooks + SOURCES.md，记录变更并提醒复检 | docs-as-code review gates, GitOps reconcile loop |
| generational GC | 优先检查最近变更文档/配置/记忆 | dirty cards, git diff, hooks |

关键边界：

- `MARK` 可自动。
- link/style/format/死引用检查可自动。
- 判断哪个来源是 truth、删除/重写文档、覆盖 config、压缩 agent memory 必须人工确认。

## 5. 对 context-gc 的 10 条落地建议

### P0 — 立即做

1. **把 `SOURCES.md` 明确定义为 root set / authority map。** 不是普通文档索引，而是每个 fact domain 的 root、copies、check command、last verified、status。

2. **给 entropy report 增加状态码。** 借鉴 CloudFormation：`SYNCED / DRIFTED / NOT_CHECKED / FORK / UNKNOWN_ROOT`。这样比单纯 emoji 更工程化。

3. **区分 MARK 与 SWEEP 的自动化边界。** MARK 自动、SWEEP 确认；尤其 deletion/overwrite/agent memory compaction 必须确认。Terraform refresh-only 与 Argo prune 都支持这个边界。

4. **把 dirty-card hooks 写成 generational GC。** 默认只检查最近被改的 context-bearing files，再按需全量扫描。

### P1 — 强化实用性

5. **加入工具适配建议而不是重造工具。** `context-gc` 不应自己实现 Vale/markdownlint/lychee，而应把它们作为可选 scanners：style scanner、structure scanner、link scanner。

6. **给 agent context rot 单独 taxonomy。** 增加 poisoning/distraction/confusion/clash 四类，对应 stale memory、tool bloat、conflicting instructions、wrong summaries。

7. **支持 exception/fork 机制。** 类似 Argo CD ignoreDifferences / markdownlint inline disable：有些 drift 是有意的，应标记 `FORK` 或 `INTENTIONAL_DIVERGENCE`，否则会产生噪音。

8. **引入 owner 字段。** 借鉴 GitLab front matter ownership，每个 fact domain 或 doc page 可指定 owner/maintainer，避免没人负责。

### P2 — 开源成熟度

9. **补 examples/demos。** 做 3 个 mini repos：doc-vs-config、agent-context-rot、kb-duplication，展示 MARK report、SWEEP plan、SOURCES.md 结果。

10. **补 CI 示例。** 给 GitHub Actions 示例：运行 `validate_context_gc.py`、lychee、markdownlint，后续可加 Vale。Hook 是本地 write barrier，CI 是远端 gate。

## 6. 对现有 context-gc 的具体改动方向

下一步建议改：

- `templates/SOURCES.md.template`：新增 status enum、owner、risk、last_checked_by。
- `references/entropy-checklist.md`：加入 config drift 状态模型与 agent context rot 四分类。
- `references/hooks.md`：明确 dirty-card = generational GC；添加 CI gate 示例。
- `SKILL.md`：报告格式加入 `UNKNOWN_ROOT` / `NOT_CHECKED` / `FORK`。
- `evals/evals.json`：新增 exception/fork 场景、agent tool-bloat 场景、dead-link 场景。

## 7. Sources

- [Write the Docs — Docs as Code](https://www.writethedocs.org/guide/docs-as-code/)
- [GitLab Documentation Contribution Guide](https://docs.gitlab.com/development/documentation/)
- [GitLab Documentation Testing](https://docs.gitlab.com/development/documentation/testing/)
- [AWS CloudFormation Drift Detection](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-stack-drift.html)
- [HashiCorp Terraform Drift Tutorial](https://developer.hashicorp.com/terraform/tutorials/state/resource-drift)
- [Argo CD Automated Sync](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
- [OpenGitOps Principles](https://opengitops.dev/)
- [Backstage TechDocs](https://backstage.io/docs/features/techdocs/)
- [Diátaxis](https://diataxis.fr/)
- [ADR GitHub](https://adr.github.io/)
- [Vale](https://vale.sh/)
- [markdownlint](https://github.com/DavidAnson/markdownlint)
- [lychee](https://github.com/lycheeverse/lychee)
- [Chroma Context Rot](https://www.trychroma.com/research/context-rot)
- [How Long Contexts Fail](https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html)
- [How to Fix Your Context](https://www.dbreunig.com/2025/06/26/how-to-fix-your-context.html)
- [Claude context management](https://claude.com/blog/context-management)
- [Manus context engineering](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
