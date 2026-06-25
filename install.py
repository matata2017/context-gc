#!/usr/bin/env python3
"""context-gc 一键安装器——下载+安装+初始化，一条命令搞定。

用法（用户只需要复制这一行到终端）：
  curl -sSL https://raw.githubusercontent.com/matata2017/context-gc/main/install.py | python3

或者让 agent 执行这一行。agent 会自动：
  1. 下载 context-gc 到 ~/.claude/skills/
  2. 扫描当前项目，写入 SOURCES.md + config.yml
  3. 打印"装好了，接下来怎么用"
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

REPO = "https://github.com/matata2017/context-gc.git"
SKILL_DIR = pathlib.Path.home() / ".claude" / "skills" / "context-gc"
TARGET = pathlib.Path.cwd()


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)


def main():
    print("═══ context-gc · 智能安装 ═══")
    print()

    # 1. 下载/更新 skill
    if SKILL_DIR.exists():
        print("[1/3] skill 已存在，更新...")
        r = run(["git", "-C", str(SKILL_DIR), "pull", "--ff-only"])
        print(f"  {'✓' if r.returncode == 0 else '(跳过)'} {SKILL_DIR}")
    else:
        print("[1/3] 下载 skill...")
        SKILL_DIR.parent.mkdir(parents=True, exist_ok=True)
        r = run(["git", "clone", "--depth", "1", REPO, str(SKILL_DIR)])
        if r.returncode != 0:
            print(f"  ✗ git clone 失败：{r.stderr}")
            return 1
        print(f"  ✓ {SKILL_DIR}")

    # 2. 初始化当前项目
    print("[2/3] 初始化项目...")
    init_py = SKILL_DIR / "scripts" / "init_context_gc.py"
    if (TARGET / "SOURCES.md").exists():
        print("  SOURCES.md 已存在，跳过 init")
    else:
        r = run([sys.executable, str(init_py), "--target", str(TARGET), "--guided", "--profile"])
        print(f"  {'✓' if r.returncode == 0 else '⚠'} SOURCES.md + config.yml")

    # 3. 完成
    print("[3/3] 完成")
    print()
    print("═══ 装好了 ═══")
    print()
    print("立即试用：")
    print(f"  python {SKILL_DIR / 'scripts' / 'gc_tick.py'} --target . --quiet")
    print()
    print("告诉你的 agent：")
    print(f'  "检查下文档有没有漂移"')
    print(f'  "跑一次 context-gc"')
    print()
    print("自检验证（可选）：")
    print(f"  python {SKILL_DIR / 'scripts' / 'validate_context_gc.py'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
