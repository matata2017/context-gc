#!/bin/bash
# context-gc 一键安装（Linux/macOS/Git Bash）
# curl -sSL https://raw.githubusercontent.com/<user>/context-gc/main/install.sh | bash
set -e

SKILL_DIR="${HOME}/.claude/skills/context-gc"
REPO="https://github.com/<user>/context-gc.git"  # TODO: 替换为真实地址
TARGET="${1:-.}"

echo "═══ context-gc 安装 ═══"
echo ""

# 1. 安装 skill 到 ~/.claude/skills/
if [ -d "$SKILL_DIR" ]; then
    echo "[1/3] skill 目录已存在，更新..."
    git -C "$SKILL_DIR" pull --ff-only 2>/dev/null || echo "  (跳过 git pull，使用现有版本)"
else
    echo "[1/3] 下载 skill..."
    git clone --depth 1 "$REPO" "$SKILL_DIR"
fi
echo "  ✓ skill 安装在 $SKILL_DIR"

# 2. 初始化目标项目
echo "[2/3] 初始化目标项目..."
if [ -f "$TARGET/SOURCES.md" ]; then
    echo "  SOURCES.md 已存在，跳过 init"
else
    python "$SKILL_DIR/scripts/init_context_gc.py" --target "$TARGET" --guided --profile
fi
echo "  ✓ 写屏障已建立"

# 3. 安装 hooks（可选）
echo "[3/3] hooks 安装..."
if [ -f "$TARGET/.claude/settings.json" ]; then
    echo "  .claude/settings.json 已存在，跳过 hook 安装"
    echo "  手动合并: $SKILL_DIR/examples/claude-settings-hooks.json"
else
    echo "  是否需要安装 hooks？（PostToolUse dirty-card + Stop 提醒）"
    echo "  后续可手动运行: python $SKILL_DIR/scripts/context_gc_hook.py --self-test"
fi

echo ""
echo "═══ 安装完成 ═══"
echo ""
echo "快速开始："
echo "  cd $TARGET"
echo "  python $SKILL_DIR/scripts/gc_tick.py --target . --quiet"
echo ""
echo "验证安装："
echo "  python $SKILL_DIR/scripts/validate_context_gc.py"
echo "  python $SKILL_DIR/scripts/context_gc_hook.py --self-test"
