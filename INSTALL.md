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

agent 会自动调 `gc_tick`，读完输出后告诉你结果。

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

Hooks 做四件事：
1. `PreToolUse` — 拦截未经批准的大范围上下文编辑
2. `PostToolUse` — 记录脏文件 → `.context-gc/dirty.jsonl`
3. 静默 auto-MARK — 脏卡达到阈值后自动跑 MARK（不打扰你）
4. `Stop` — 会话结束时有待决漂移会提醒你

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
