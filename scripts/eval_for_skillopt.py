#!/usr/bin/env python3
"""context-gc → SkillOpt 自动评分器。

SkillOpt 需要一个 EnvAdapter，其 rollout() 方法返回:
  [{"id": "eval-name", "hard": 0/1, "soft": 0.0-1.0}, ...]

此脚本提供两种评分模式:
  --mode static  免费、快速、离线——检查 SKILL.md 文本是否包含 eval 要求的术语
  --mode llm     调用 LLM API 实际运行 eval + 裁判评分（更准，但有成本）

LLM 后端自动检测: DEEPSEEK_API_KEY → DeepSeek, ANTHROPIC_API_KEY → Claude, 都未设置则报错

用法:
  # 静态评分（推荐先跑）
  python eval_for_skillopt.py --skill SKILL.md --mode static

  # DeepSeek 评分
  export DEEPSEEK_API_KEY=sk-...
  python eval_for_skillopt.py --skill SKILL.md --mode llm --model deepseek-chat

  # Claude 评分
  export ANTHROPIC_API_KEY=sk-ant-...
  python eval_for_skillopt.py --skill SKILL.md --mode llm --model claude-sonnet-4-6

  # 输出 SkillOpt 兼容格式
  python eval_for_skillopt.py --skill SKILL.md --mode static --skillopt-format
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
EVALS_PATH = ROOT / "evals" / "evals.json"


def load_evals() -> list[dict]:
    return json.loads(EVALS_PATH.read_text(encoding="utf-8")).get("evals", [])


def load_skill(skill_path: str) -> str:
    p = pathlib.Path(skill_path)
    if not p.exists():
        # Try relative to project root
        p = ROOT / skill_path
    if not p.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")
    return p.read_text(encoding="utf-8")


# -- 静态评分器（免费、离线）--------------------------------------------------

def _score_static_eval(eval_item: dict, skill_text: str) -> dict:
    """检查 SKILL.md 文本是否包含 eval 期望的术语和模式。"""
    name = eval_item["name"]
    assertions = eval_item.get("assertions", [])

    # 从 assertions 中提取关键术语
    key_terms: list[str] = []
    for a in assertions:
        # 提取断言中的关键名词
        words = a.lower().replace(",", " ").replace(".", " ").split()
        # 过滤掉太通用的词
        skip = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                "does", "not", "or", "and", "of", "in", "to", "for", "with",
                "as", "at", "by", "on", "that", "this", "it", "from"}
        meaningful = [w for w in words if w not in skip and len(w) > 2]
        key_terms.extend(meaningful[:5])  # 取前 5 个有意义的词

    # 去重
    key_terms = list(dict.fromkeys(key_terms))

    # 检查 SKILL.md 文本是否包含这些术语
    skill_lower = skill_text.lower()
    hits = sum(1 for t in key_terms if t in skill_lower)
    soft = hits / max(len(key_terms), 1)

    # Hard pass = SKILL.md 覆盖了这个 eval 绝大多数能力关键词（命中率 ≥ 0.8）。
    # 这是"文本覆盖"的代理指标，不是真正的行为评分——真行为评分用 --mode llm。
    hard = 1.0 if soft >= 0.8 else 0.0

    return {
        "id": name,
        "hard": round(hard, 4),
        "soft": round(soft, 4),
    }


def static_evaluate(skill_text: str, eval_subset: list[dict] | None = None) -> list[dict]:
    """对一组 eval 运行静态评分。eval_subset=None 时跑全部。"""
    evals = eval_subset if eval_subset is not None else load_evals()
    return [_score_static_eval(ev, skill_text) for ev in evals]


# -- LLM 后端（DeepSeek / Claude 自适应）-------------------------------------

def _build_eval_prompt(eval_item: dict, skill_text: str) -> str:
    """构建"运行 eval"的 prompt——模拟用户向带 SKILL.md 的 agent 提问。"""
    prompt = eval_item.get("prompt", "")
    files = eval_item.get("files", {})
    files_str = "\n".join(f"  {k}:\n```\n{v}\n```" for k, v in files.items())
    return f"""You are an agent with this SKILL.md loaded:

---
{skill_text[:8000]}
---

The user's project has these files:

{files_str}

The user says: "{prompt}"

Respond as the agent would, following the SKILL.md instructions."""


def _build_judge_prompt(eval_item: dict, agent_response: str) -> str:
    """构建裁判 prompt——检查 agent 回复是否满足 eval 要求。"""
    expected = eval_item.get("expected_output", "")
    assertions = eval_item.get("assertions", [])

    assertion_list = "\n".join(f"{i+1}. {a}" for i, a in enumerate(assertions))

    return f"""You are an evaluator. Judge whether the agent's response satisfies the expected output
and assertions. Return JSON only, no other text.

## Expected output
{expected}

## Assertions to check
{assertion_list}

## Agent's response
{agent_response[:4000]}

Return JSON:
{{"assertions_pass": [true, false, ...], "overall_pass": true/false, "partial_score": 0.0-1.0,
 "explanation": "one sentence"}}"""


def _call_llm(prompt: str, model: str, max_tokens: int = 2048) -> str:
    """调用 LLM API——自动检测 DeepSeek 或 Claude。"""
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if deepseek_key:
        return _call_deepseek(prompt, model, max_tokens, deepseek_key)
    elif anthropic_key:
        return _call_claude(prompt, model, max_tokens, anthropic_key)
    else:
        return json.dumps({"error": "Set DEEPSEEK_API_KEY or ANTHROPIC_API_KEY"})


def _call_deepseek(prompt: str, model: str, max_tokens: int, api_key: str) -> str:
    """调用 DeepSeek API（OpenAI 兼容接口）。"""
    import urllib.request as ur

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }).encode("utf-8")

    req = ur.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with ur.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except Exception as exc:
        return json.dumps({"error": f"DeepSeek API error: {exc}"})


def _call_claude(prompt: str, model: str, max_tokens: int, api_key: str) -> str:
    """调用 Claude API。"""
    try:
        from anthropic import Anthropic
    except ImportError:
        return json.dumps({"error": "anthropic SDK not installed. pip install anthropic"})

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def llm_evaluate(skill_text: str, model: str = "claude-sonnet-4-6", max_evals: int | None = None,
                 eval_subset: list[dict] | None = None, samples: int = 1) -> list[dict]:
    """对一组 eval 运行 LLM 评分。⚠️ 有成本——每个 eval ~2*samples 次 LLM 调用。

    eval_subset: 显式指定要跑的 eval 列表（优化器用，按 train/valid split 传入）；
                 None 时跑全部（可用 max_evals 截断前 N 个）。
    samples:     每个 eval 评分几次取共识（hard 多数票、soft 中位数）。LLM-as-judge 有方差，
                 samples=1 的单次分会噪声很大，让优化变成赌运气；samples>=3 才让分数可信。
    """
    evals = eval_subset if eval_subset is not None else load_evals()
    if max_evals:
        evals = evals[:max_evals]

    results = []
    for i, ev in enumerate(evals):
        name = ev["name"]
        print(f"  [{i+1}/{len(evals)}] {name}...", file=sys.stderr, flush=True, end=" ")
        hards: list[float] = []
        softs: list[float] = []
        for _ in range(max(1, samples)):
            h, s = _score_one(ev, skill_text, model)
            hards.append(h)
            softs.append(s)
            time.sleep(0.3)
        # hard: 多数票（>=半数为 1 才算 1）；soft: 中位数（抗离群）
        hard = 1.0 if sum(hards) * 2 >= len(hards) else 0.0
        soft = round(_median(softs), 4)
        results.append({"id": name, "hard": hard, "soft": soft})
        tag = f"hard={hard} soft={soft}" + (f" (n={samples} hards={hards})" if samples > 1 else "")
        print(tag, file=sys.stderr)

    return results


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _score_one(eval_item: dict, skill_text: str, model: str) -> tuple[float, float]:
    """单次评分：agent 回答 → judge 打分 → (hard, soft)。"""
    try:
        agent_prompt = _build_eval_prompt(eval_item, skill_text)
        agent_response = _call_llm(agent_prompt, model, max_tokens=4096)
        judge_prompt = _build_judge_prompt(eval_item, agent_response)
        judge_response = _call_llm(judge_prompt, model, max_tokens=1024)
        try:
            verdict = json.loads("{" + judge_response.strip().split("{", 1)[-1].rsplit("}", 1)[0] + "}")
        except Exception:
            # Fallback: agent 回复是否提到期望输出关键词
            keywords = eval_item.get("expected_output", "").lower().split()
            hits = sum(1 for k in keywords if k in agent_response.lower())
            soft = hits / max(len(keywords), 1)
            verdict = {"overall_pass": soft > 0.5, "partial_score": round(soft, 2)}
        hard = 1.0 if verdict.get("overall_pass", False) else 0.0
        soft = round(verdict.get("partial_score", 0.0), 4)
        return hard, soft
    except Exception as exc:
        print(f"[score error: {exc}]", file=sys.stderr, end=" ")
        return 0.0, 0.0


# -- 聚合输出 ----------------------------------------------------------------

def aggregate(results: list[dict]) -> dict:
    n = len(results)
    hard_sum = sum(r["hard"] for r in results)
    soft_sum = sum(r["soft"] for r in results)
    return {
        "total_evals": n,
        "hard_pass": int(hard_sum),
        "hard_score": round(hard_sum / n, 4) if n else 0,
        "soft_score": round(soft_sum / n, 4) if n else 0,
        "results": results,
    }


def print_skillopt_format(results: list[dict]) -> None:
    """SkillOpt 兼容格式输出。"""
    for r in results:
        print(json.dumps(r, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser(description="context-gc auto-evaluator for SkillOpt")
    ap.add_argument("--skill", default="SKILL.md", help="path to SKILL.md (default: SKILL.md)")
    ap.add_argument("--mode", choices=["static", "llm"], default="static",
                    help="static = free offline term check | llm = Claude API judge")
    ap.add_argument("--model", default="claude-sonnet-4-6", help="model for LLM mode")
    ap.add_argument("--max-evals", type=int, default=None, help="limit evals (LLM mode)")
    ap.add_argument("--samples", type=int, default=1,
                    help="LLM mode: score each eval N times, take consensus (hard=majority, soft=median). Use >=3 to beat judge variance.")
    ap.add_argument("--skillopt-format", action="store_true",
                    help="output SkillOpt-compatible JSONL: {id, hard, soft} per line")
    args = ap.parse_args()

    try:
        skill_text = load_skill(args.skill)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.mode == "static":
        results = static_evaluate(skill_text)
    else:
        results = llm_evaluate(skill_text, model=args.model, max_evals=args.max_evals, samples=args.samples)

    if args.skillopt_format:
        print_skillopt_format(results)
        return 0

    agg = aggregate(results)
    print(json.dumps({
        "mode": args.mode,
        "skill": args.skill,
        "hard_score": agg["hard_score"],
        "soft_score": agg["soft_score"],
        "hard_pass": agg["hard_pass"],
        "total_evals": agg["total_evals"],
    }, ensure_ascii=False, indent=2))

    # 打印细节
    print("\n--- detail ---", file=sys.stderr)
    for r in results:
        marker = "✓" if r["hard"] >= 1.0 else ("◐" if r["soft"] >= 0.5 else "✗")
        print(f"  {marker} {r['id']}: hard={r['hard']} soft={r['soft']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
