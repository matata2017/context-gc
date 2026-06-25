# SkillOpt 集成 — 自我进化能力 + 一个关于评分方差的真实教训

> 2026-06-26 · 用微软 SkillOpt（arXiv 2605.23904）的思想优化 context-gc 自己的 SKILL.md。
> 关联：[`scripts/eval_for_skillopt.py`](../scripts/eval_for_skillopt.py)、
> [`scripts/skillopt_optimize.py`](../scripts/skillopt_optimize.py)、
> [`references/loop-engineering.md`](../references/loop-engineering.md)（Layer 4 爬坡循环）。

## 一句话

context-gc 用 SkillOpt 的方法优化自己的 SKILL.md——这是 Loop Engineering 第四层"爬坡循环"
（让 AI 优化它自己的工作方式）在本项目的真实落地，不再是空理论。过程中发现并修复了一个会让
整个优化流程失效的真问题：**LLM-as-judge 评分有严重方差，单次评分会制造假的优化胜利。**

## 为什么做这个

SKILL.md 是给**所有 agent** 用的治理协议，不是给 Claude 专用。一个真正通用的 skill，应该在任何
agent（Claude、DeepSeek、Hermes 里的任意 worker）读它时都能讲清楚该做什么。用 DeepSeek 当裁判
优化出来的 SKILL.md，恰恰证明它对非 Claude 的 agent 也成立——这是加分项，不是减分项。

目标尤其是**自主调用**：让 agent 自己判断该治理漂移了，而不是等人喊"跑 context-gc"。Hermes loop
里没有人坐着喊命令，agent 得自己知道什么时候该跑。

## 架构

两个零依赖脚本，复用项目已有的 `evals/evals.json`：

```
eval_for_skillopt.py   评分器
  - static 模式：免费离线，检查 SKILL.md 是否覆盖 eval 的能力关键词
  - llm 模式：真 agent+judge 评分，DEEPSEEK_API_KEY / ANTHROPIC_API_KEY 自动切换
  - --samples N：每个 eval 评分 N 次取共识（hard 多数票、soft 中位数）← 关键

skillopt_optimize.py   优化循环（rollout→reflect→gate→update）
  - train/valid split，valid 集门控
  - reflect：optimizer 模型读失败 eval，提一个有界 add/replace 编辑
  - gate：候选只有在 valid 集严格提升才接受，否则拒绝回滚
```

## 核心教训：评分方差会制造假胜利

### 现象

同一个 SKILL.md、同一个 eval，单次 LLM 评分连跑 3 次：

```
run 1: soft=0.8     run 2: soft=0.0     run 3: soft=0.2
```

soft 在 0.0–0.8 之间跳。hard（pass/fail）也跳：`[1,0,1,1,0]`。单看任何一次都不可信。

### 后果：两轮优化，两个结论

| | 单次评分（samples=1） | 稳定评分（samples=3） |
|---|---|---|
| baseline valid hard | 0.20 | 0.36 |
| epoch 1 | accept（→0.4） | **reject**（0.27 < 0.36，门控拦截） |
| epoch 2 | accept（→0.5） | 进行中 |
| 结论 | "优化成功 0.2→0.5" | "假提升被门控正确拦截" |

**单次评分那轮报告的"优化成功"，有一半是 judge 噪声制造的假象。** 同样的 optimizer、同样的编辑，
在稳定评分下 epoch 1 直接被拒——因为那个编辑实际让分数掉了，只是单次评分时 judge 恰好心情好。

### 修复

`--samples N`：每个 eval 评分 N 次，hard 取多数票、soft 取中位数。验证：

```
samples=5 共识，同一 eval 跑 2 次：
  trial 1: hard=1.0 (单次 hards=[1,0,1,1,0])
  trial 2: hard=1.0 (单次 hards=[1,1,0,1,1])
```

单次在 1/0 之间跳，5 次多数票两轮都稳定收敛。**把不稳定的判断变成可信的根**——这正是 context-gc
自己的第一原则：不稳定的判断不能当真相的根。

### 这条教训的普适价值

任何用 LLM-as-judge 做优化/评估的系统都吃这个亏：
- 单次评分 = 在噪声上做决策，优化变成赌运气。
- 微软 SkillOpt 论文用三招对抗：judge temperature=0、多次采样、valid 严格门控。
- DeepSeek 的 temperature=0 仍不够确定性 → 多次采样是必需，不是可选。

## 自主触发：真正要优化的目标

当前 SKILL.md 在自主触发场景下，稳定评分暴露出比表面更弱：agent 跟着走方向对（soft 中等）但
没完全照做（hard 低）。根因是 SKILL.md 正文的 `When an agent is driving` 段落太笼统——只说"做完事
跑 gc_tick"，没说清 agent 该在哪些**具体信号点**主动跑。

为此加了 6 个自主触发 eval（#30–35），覆盖 5 大类信号。完整矩阵见 README 的 "Autonomous triggers"
章节。最关键的是 `autonomous-verify-gate-before-done`——agent 在"我做完了"这个判断点自己跑
`gc_tick --gate`，这是 Hermes loop 的核心接入点。

## 结论

1. **基础设施是真资产**：评分器 + 门控 + 多次采样，是任何 LLM 优化系统都该有的。没有稳定评分，
   你根本分不清一个优化是真的还是假的。
2. **optimizer 模型有天花板**：DeepSeek 的"加一段澄清句"在严格门控下不易一次命中真提升。论文用
   GPT-5.5，模型越强编辑越精准。这不是工具的问题，是 optimizer 模型的力道。
3. **门控正确工作 = 好结果**：epoch 1 候选被拒，证明门控在防止把 skill 改坏。诚实的拒绝胜过虚假的接受。

## 怎么用

```bash
export DEEPSEEK_API_KEY=sk-...   # 或 ANTHROPIC_API_KEY

# 评分（看 SKILL.md 当前多少分，稳定评分）
python scripts/eval_for_skillopt.py --skill SKILL.md --mode llm --samples 3

# 优化一轮
python scripts/skillopt_optimize.py --skill SKILL.md --epochs 2 --samples 3
# → outputs/<run>/best_skill.md（人 review 后再手动合，不自动覆盖 SKILL.md）
```

**永远人 review 优化产物再合**——optimizer 提的编辑可能命中、可能跑偏，门控只保证"不退步"，
不保证"加进去的内容你认同"。
