# 告诉你的 agent，它来装

复制下面这段话，发给你的 agent（Claude Code、Cursor、MiniMax Code、任何）：

---

```
安装 context-gc 到当前项目：

1. 如果 ~/.claude/skills/context-gc 不存在：
   git clone https://github.com/<user>/context-gc.git ~/.claude/skills/context-gc

2. 运行：
   python ~/.claude/skills/context-gc/scripts/init_context_gc.py --target . --guided --profile

3. 告诉我：装好了，SOURCES.md 和 config.yml 在哪里，接下来怎么用。
```

---

agent 会自己 clone、自己跑 init、自己汇报结果。你什么都不用做。

装完之后和 agent 说 "检查下漂移" 就行。
