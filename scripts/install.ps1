# context-gc 一键安装（Windows PowerShell）
# irm https://raw.githubusercontent.com/<user>/context-gc/main/install.ps1 | iex

param(
    [string]$Target = ".",
    [string]$SkillDir = "$env:USERPROFILE\.claude\skills\context-gc",
    [string]$Repo = "https://github.com/<user>/context-gc.git"
)

Write-Host "═══ context-gc 安装 ═══" -ForegroundColor Cyan
Write-Host ""

# 1. 安装 skill 到 ~/.claude/skills/
Write-Host "[1/3] 安装 skill..." -ForegroundColor Yellow
if (Test-Path $SkillDir) {
    Write-Host "  skill 目录已存在：$SkillDir"
    try { git -C $SkillDir pull --ff-only 2>$null } catch { Write-Host "  (跳过 git pull，使用现有版本)" }
} else {
    New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
    git clone --depth 1 $Repo $SkillDir
}
Write-Host "  ✓ skill 已安装：$SkillDir" -ForegroundColor Green

# 2. 初始化目标项目
Write-Host "[2/3] 初始化目标项目..." -ForegroundColor Yellow
$targetPath = (Resolve-Path $Target).Path
if (Test-Path "$targetPath\SOURCES.md") {
    Write-Host "  SOURCES.md 已存在，跳过 init"
} else {
    python "$SkillDir\scripts\init_context_gc.py" --target $targetPath --guided --profile
}
Write-Host "  ✓ 写屏障已建立" -ForegroundColor Green

# 3. hooks 提示
Write-Host "[3/3] hooks..." -ForegroundColor Yellow
$settingsPath = "$targetPath\.claude\settings.json"
if (Test-Path $settingsPath) {
    Write-Host "  .claude/settings.json 已存在，跳过"
    Write-Host "  手动合并：$SkillDir\examples\claude-settings-hooks.json"
} else {
    Write-Host "  运行 python $SkillDir\scripts\context_gc_hook.py --self-test 验证 hook 环境"
    Write-Host "  hook 配置模板：$SkillDir\examples\claude-settings-hooks.json"
}

Write-Host ""
Write-Host "═══ 安装完成 ═══" -ForegroundColor Cyan
Write-Host ""
Write-Host "立即试用："
Write-Host "  python $SkillDir\scripts\gc_tick.py --target . --quiet"
Write-Host ""
Write-Host "自检验证："
Write-Host "  python $SkillDir\scripts\validate_context_gc.py"
Write-Host "  python $SkillDir\scripts\run_evals.py"
