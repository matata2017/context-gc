# 告诉你的 agent，它来装

复制下面这段话，发给你的 agent（Claude Code、Cursor、MiniMax Code、任何）：

---

```
安装 context-gc 到当前项目：

1. 如果 ~/.claude/skills/context-gc 不存在：
   git clone https://github.com/matata2017/context-gc.git ~/.claude/skills/context-gc

2. 运行（一条命令 = 建写屏障 + hands-off 接管 + 首次全量体检）：
   python ~/.claude/skills/context-gc/scripts/init_context_gc.py --target . --guided --profile --takeover

3. 把它打印的"接管总结 + 存量漂移清单"念给我；之后你在后台自动守护漂移，只在需要我拍板时再找我。
```

---

agent 会自己 clone、自己跑 init、自己汇报结果。你什么都不用做。

装完之后和 agent 说 "检查下漂移" 就行。
