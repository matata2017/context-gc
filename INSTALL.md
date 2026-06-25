# Installation

## 一键安装

**Windows（PowerShell）：**

```powershell
git clone https://github.com/matata2017/context-gc.git $env:USERPROFILE\.claude\skills\context-gc
cd <你的项目目录>
python $env:USERPROFILE\.claude\skills\context-gc\scripts\init_context_gc.py --target . --guided --profile
```

**macOS / Linux：**

```bash
git clone https://github.com/matata2017/context-gc.git ~/.claude/skills/context-gc
cd <你的项目>
python ~/.claude/skills/context-gc/scripts/init_context_gc.py --target . --guided --profile
```

**安装完成后，三秒试用：**

```bash
python ~/.claude/skills/context-gc/scripts/gc_tick.py --target . --quiet
# 输出：context-gc tick: auto_fixed=0 agent_resolved=0 escalated=0 pending=0 (level=assist)
```

---

## 安装后 agent 怎么用

安装完你的 agent 就会用了。说这些触发词即可：

- "检查下文档有没有漂移" / "跑一次 context-gc"
- "这两个配置对不上了，看看谁是真的"  
- "知识库膨胀了，压缩一下"

agent 会自动调 `gc_tick`，读完输出后告诉你结果。`gc_tick` 是 agent 自主调用的主入口——
它链式跑 mark → minor_gc → review_queue → resolve，永不阻塞，还会**自动感知 git 分支切换**
（切分支时旧脏卡失效、按新分支重新检测，不会跨分支误报）。

**如果你的 agent 平台不支持 Claude Code skill，没关系——给它这个指令：**

```markdown
## 我的漂移治理规则

每次代码/文档变更后，运行：
```bash
python ~/.claude/skills/context-gc/scripts/gc_tick.py --target . --quiet
```
- auto_fixed=N → N 个漂移已自动修复，没事
- escalated=N → N 个项需要我决策，打开 .context-gc/review-queue.json 告诉我
```

### 接进 loop 引擎（Hermes / Ralph / LangGraph）

如果你跑的是无人值守的 loop，用对应的 adapter 把 context-gc 接成验证关卡：

```bash
# Hermes / Ralph：三个命令对应 verify / 升级任务 / 压缩 loop 自身记忆
python ~/.claude/skills/context-gc/scripts/adapters/hermes_adapter.py gate --target .
python ~/.claude/skills/context-gc/scripts/adapters/hermes_adapter.py emit-tasks --target . --output queue.md
python ~/.claude/skills/context-gc/scripts/adapters/hermes_adapter.py compact --target . --context CONTEXT.md --progress PROGRESS.md

# LangGraph：打印一个可直接粘进图的验证节点
python ~/.claude/skills/context-gc/scripts/adapters/langgraph_adapter.py template
```

把 `gate` 配成 loop 的 `verify_cmd`：任务完成后跑一次，引入了消不掉的漂移 → exit 1 → loop 重试。
完整接入示例见 [`references/architecture.md`](references/architecture.md) 的 Hermes 集成实例。

---

## 手动安装（分步）

### 1. 安装 skill

将仓库复制到 Claude skills 目录：

**Windows:**
```powershell
Copy-Item -Recurse D:\context-gc $env:USERPROFILE\.claude\skills\context-gc
```

**macOS / Linux:**
```bash
cp -r ./context-gc ~/.claude/skills/context-gc
```

重载 skills：
```
/reload-skills
```

### 2. 初始化项目

在目标项目目录下建立写屏障：

```bash
python ~/.claude/skills/context-gc/scripts/init_context_gc.py --target . --guided --profile
```

这会：
- 扫描项目里的所有上下文文件（文档、配置、agent 指令、memory）
- 写入 `SOURCES.md`（权威地图骨架）
- 写入 `.context-gc/config.yml`（安全默认：只观察，不自动编辑）
- 对模糊的根弹出 AskUserQuestion 让你确认

### 3. （可选）安装 hooks

把 `examples/claude-settings-hooks.json` 合并到项目的 `.claude/settings.json`。

Hooks 做这些事（对应 `examples/claude-settings-hooks.json` 里配的子命令）：
1. `PreToolUse` → `sweep-guard` — 拦截未经批准的大范围上下文编辑
2. `PostToolUse` → `dirty-card` — 记录脏文件 → `.context-gc/dirty.jsonl`
3. `Stop` → `stop-reminder` — 会话结束时：脏卡达阈值则静默跑 auto-MARK，预防性 Minor GC
   自动应用预授权安全修复（仅 `apply_safe: true` 时），有待决漂移则一行提示你 `/context-gc review`

所有 hook 都只读/只记录/只在授权范围内安全修复——永不静默 SWEEP，永不碰 `never_auto` 红线。

验证 hook 环境：
```bash
python ~/.claude/skills/context-gc/scripts/context_gc_hook.py --self-test
```

---

## 接入任何 agent 平台

context-gc 不绑定 Claude Code。**任何能执行命令的 agent 都能用。**

| 平台 | 接入方式 |
|---|---|
| **Claude Code** | Skill（自动触发）+ Hook（事件驱动） |
| **Cursor / Windsurf** | `.cursor/rules` / `.windsurfrules` 里写 "每次改完文档跑 gc_tick" |
| **Cline / Roo Code** | 项目规则文件里加 gc_tick 指令 |
| **GitHub Copilot** | `.github/copilot-instructions.md` 加 gc_tick 提示 |
| **MiniMax Code / 其他** | 同上——在项目规则里加 gc_tick 指令 |
| **CI / GitHub Actions** | `python scripts/gc_tick.py --target . --quiet` 作为流水线一步 |
| **自有 agent 框架** | `subprocess.run(["python", "scripts/gc_tick.py", ...])` 或调 MCP |
| **Hermes / Loop 引擎** | `hermes_adapter.py gate` 作为 verify_cmd |

本质就是一行命令。所有 agent 都会。

---

## CI 集成

```yaml
# .github/workflows/drift-check.yml
- name: Drift gate
  run: python ~/.claude/skills/context-gc/scripts/gc_tick.py --target . --quiet
```

输出里 `escalated > 0` 可以配置为 CI 警告或 block deploy。

---

## 验证安装

```bash
python ~/.claude/skills/context-gc/scripts/validate_context_gc.py
python ~/.claude/skills/context-gc/scripts/run_evals.py
python ~/.claude/skills/context-gc/scripts/context_gc_hook.py --self-test
```

三条都绿 = 安装正确。
