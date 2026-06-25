#!/usr/bin/env python3
"""SkillOpt 本地优化循环——用 LLM 迭代优化 SKILL.md，验证集门控。

微软 SkillOpt 的核心思想（arXiv 2605.23904）：像训神经网络一样训 skill 文档——
optimizer 模型把"打分后的 rollout"变成对单个 skill 文档的有界 add/delete/replace 编辑，
一个候选编辑只有在严格提升 held-out 验证分时才被接受。

本脚本是该思想的零依赖本地实现，复用 eval_for_skillopt 的评分器：

  每个 epoch:
    1. rollout   —— 在 train 集上给当前 SKILL.md 评分（LLM agent + judge）
    2. reflect   —— optimizer 模型读失败的 eval（assertions 未满足），提出 SKILL.md 编辑
    3. gate      —— 在 valid 集上给候选评分；只有严格提升才接受（否则拒绝、回滚）
    4. update    —— 接受则成为新 current；记录历史

输出:
  outputs/<run>/best_skill.md       最优 SKILL.md
  outputs/<run>/history.json        每个 epoch 的分数 + 接受/拒绝
  outputs/<run>/skill_ep<N>.md      每个 epoch 的快照

用法:
  export DEEPSEEK_API_KEY=sk-...
  python scripts/skillopt_optimize.py --skill SKILL.md --epochs 3 --model deepseek-chat
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import eval_for_skillopt as ev  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def split_evals(seed: int, valid_frac: float = 0.35) -> tuple[list[dict], list[dict]]:
    """把 eval 集切成 train / valid。valid 用于门控，train 用于反思。"""
    evals = ev.load_evals()
    rng = random.Random(seed)
    shuffled = evals[:]
    rng.shuffle(shuffled)
    n_valid = max(1, int(len(shuffled) * valid_frac))
    valid = shuffled[:n_valid]
    train = shuffled[n_valid:]
    return train, valid


def score(skill_text: str, subset: list[dict], model: str, mode: str, samples: int = 3) -> dict:
    """给一组 eval 评分，返回聚合分。LLM 模式默认 samples=3 取共识，抗 judge 方差。"""
    if mode == "static":
        results = ev.static_evaluate(skill_text, eval_subset=subset)
    else:
        results = ev.llm_evaluate(skill_text, model=model, eval_subset=subset, samples=samples)
    n = len(results)
    hard = sum(r["hard"] for r in results) / n if n else 0.0
    soft = sum(r["soft"] for r in results) / n if n else 0.0
    return {"hard": round(hard, 4), "soft": round(soft, 4), "results": results}


def _failures(skill_text: str, subset: list[dict], model: str, mode: str, samples: int = 3) -> list[dict]:
    """找出未通过的 eval（hard < 1），附带它们的断言，供反思。"""
    sc = score(skill_text, subset, model, mode, samples=samples)
    by_id = {r["id"]: r for r in sc["results"]}
    fails = []
    for e in subset:
        r = by_id.get(e["name"], {})
        if r.get("hard", 0) < 1.0:
            fails.append({
                "name": e["name"],
                "prompt": e.get("prompt", ""),
                "expected": e.get("expected_output", ""),
                "assertions": e.get("assertions", []),
                "soft": r.get("soft", 0),
            })
    return fails, sc


def _build_reflect_prompt(skill_text: str, failures: list[dict]) -> str:
    """构建 optimizer prompt——读失败案例，提出对 SKILL.md 的有界编辑。"""
    # 只取最差的 5 个，控制 token
    worst = sorted(failures, key=lambda f: f["soft"])[:5]
    fail_blocks = []
    for f in worst:
        assertions = "\n".join(f"      - {a}" for a in f["assertions"])
        fail_blocks.append(
            f"  EVAL: {f['name']} (current soft={f['soft']})\n"
            f"    user prompt: {f['prompt']}\n"
            f"    expected: {f['expected']}\n"
            f"    assertions not satisfied:\n{assertions}"
        )
    fails_str = "\n\n".join(fail_blocks)

    return f"""You are optimizing a Claude Code SKILL.md so an agent following it satisfies more eval assertions.

## Current SKILL.md
---
{skill_text}
---

## Evals the agent is currently failing
{fails_str}

## Your task
Propose a SINGLE bounded edit to SKILL.md that would help the agent satisfy more of the failing
assertions, WITHOUT breaking what already works. Keep the skill's structure and voice. Prefer adding
a concise clarifying sentence or a missing instruction over large rewrites.

Return JSON only:
{{"edit_type": "add" | "replace",
  "anchor": "<exact existing line/heading the edit attaches after, or the exact text to replace>",
  "new_text": "<the text to add after the anchor, or the replacement text>",
  "rationale": "<one sentence: which assertions this helps>"}}"""


def _apply_edit(skill_text: str, edit: dict) -> str | None:
    """应用一个 add/replace 编辑。返回新文本，失败返回 None。"""
    etype = edit.get("edit_type", "")
    anchor = edit.get("anchor", "")
    new_text = edit.get("new_text", "")
    if not anchor or not new_text:
        return None
    if anchor not in skill_text:
        return None
    if etype == "replace":
        return skill_text.replace(anchor, new_text, 1)
    if etype == "add":
        # 在 anchor 后插入
        idx = skill_text.find(anchor) + len(anchor)
        return skill_text[:idx] + "\n" + new_text + skill_text[idx:]
    return None


def optimize(skill_path: str, epochs: int, model: str, mode: str, seed: int, run_name: str, samples: int = 3) -> dict:
    skill_file = pathlib.Path(skill_path)
    if not skill_file.exists():
        skill_file = ROOT / skill_path
    current = skill_file.read_text(encoding="utf-8")

    train, valid = split_evals(seed)
    out_dir = ROOT / "outputs" / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[skillopt] train={len(train)} valid={len(valid)} mode={mode} model={model}", file=sys.stderr)

    # baseline 验证分
    base_valid = score(current, valid, model, mode, samples=samples)
    best_valid = base_valid
    best_skill = current
    history = [{"epoch": 0, "action": "baseline", "valid_hard": base_valid["hard"], "valid_soft": base_valid["soft"]}]
    print(f"[skillopt] baseline valid: hard={base_valid['hard']} soft={base_valid['soft']}", file=sys.stderr)

    for epoch in range(1, epochs + 1):
        print(f"\n[skillopt] === epoch {epoch}/{epochs} ===", file=sys.stderr)

        # 1) reflect on train failures
        fails, train_sc = _failures(current, train, model, mode, samples=samples)
        print(f"[skillopt] train: hard={train_sc['hard']} soft={train_sc['soft']} ({len(fails)} failing)", file=sys.stderr)
        if not fails:
            print("[skillopt] no train failures — stopping early", file=sys.stderr)
            break

        reflect_prompt = _build_reflect_prompt(current, fails)
        reflect_out = ev._call_llm(reflect_prompt, model, max_tokens=2048)
        try:
            edit = json.loads("{" + reflect_out.strip().split("{", 1)[-1].rsplit("}", 1)[0] + "}")
        except Exception as exc:
            history.append({"epoch": epoch, "action": "reject", "reason": f"unparseable edit: {exc}"})
            print(f"[skillopt] epoch {epoch}: optimizer returned unparseable edit, skipping", file=sys.stderr)
            continue

        # 2) apply edit
        candidate = _apply_edit(current, edit)
        if candidate is None or candidate == current:
            history.append({"epoch": epoch, "action": "reject", "reason": "edit did not apply (anchor not found)"})
            print(f"[skillopt] epoch {epoch}: edit anchor not found, skipping", file=sys.stderr)
            continue

        # 3) gate on valid
        cand_valid = score(candidate, valid, model, mode, samples=samples)
        improved = (cand_valid["hard"], cand_valid["soft"]) > (best_valid["hard"], best_valid["soft"])
        action = "accept" if improved else "reject"
        history.append({
            "epoch": epoch,
            "action": action,
            "rationale": edit.get("rationale", ""),
            "valid_hard": cand_valid["hard"],
            "valid_soft": cand_valid["soft"],
        })
        print(f"[skillopt] epoch {epoch}: candidate valid hard={cand_valid['hard']} soft={cand_valid['soft']} → {action}", file=sys.stderr)

        # 4) update
        (out_dir / f"skill_ep{epoch}.md").write_text(candidate, encoding="utf-8")
        if improved:
            current = candidate
            best_valid = cand_valid
            best_skill = candidate

    (out_dir / "best_skill.md").write_text(best_skill, encoding="utf-8")
    summary = {
        "run": run_name,
        "model": model,
        "mode": mode,
        "epochs": epochs,
        "baseline_valid": {"hard": base_valid["hard"], "soft": base_valid["soft"]},
        "best_valid": {"hard": best_valid["hard"], "soft": best_valid["soft"]},
        "improved": (best_valid["hard"], best_valid["soft"]) > (base_valid["hard"], base_valid["soft"]),
        "history": history,
    }
    (out_dir / "history.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="SkillOpt local optimization loop for context-gc SKILL.md")
    ap.add_argument("--skill", default="SKILL.md")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--mode", choices=["static", "llm"], default="llm",
                    help="static = free offline scoring | llm = real agent+judge (costs API calls)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--samples", type=int, default=3,
                    help="每个 eval 评分几次取共识（抗 judge 方差）。LLM 模式建议 >=3。")
    ap.add_argument("--run-name", default=None)
    args = ap.parse_args()

    run_name = args.run_name or f"run-{int(time.time())}"
    summary = optimize(args.skill, args.epochs, args.model, args.mode, args.seed, run_name, samples=args.samples)

    print(json.dumps({
        "run": summary["run"],
        "baseline_valid": summary["baseline_valid"],
        "best_valid": summary["best_valid"],
        "improved": summary["improved"],
        "output": f"outputs/{run_name}/best_skill.md",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
