# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@SKILL.md

## Project context

`context-gc` is itself a Claude Code skill — a drift-governance toolkit for docs, configs, SDDs,
knowledge bases, and agent context. The repo dogfoods its own write barrier (`SOURCES.md`).

## Validation commands

```bash
python scripts/validate_context_gc.py    # structural checks + dogfood self-audit
python scripts/run_evals.py              # offline eval fixture checker
python scripts/context_gc_hook.py --self-test   # hook helper parser + guard checks
```

## Architecture

Scripts are deterministic and non-interactive; they emit machine-readable JSON/Markdown under
`.context-gc/` and never edit project files without an explicit safety gate. The SKILL workflow
owns all human interaction (AskUserQuestion).

Key runners:
- `mark.py` — read-only drift detection (orphans, duplicates, stale docs, agent/memory checks)
- `minor_gc.py` — preventive GC with pre-authorized safe fixers (scalar-sync, pointer-copy, etc.)
- `review_queue.py` — aggregates open decisions into `.context-gc/review-queue.json`
- `resolve.py` — agent self-resolve within `autonomy` policy; `--log` prints audit trail
- `gc_tick.py` — one governance tick any loop engine can call
- `session_mark.py` — MARK on exported session transcripts

## Safety rules (never violate these)

- MARK is read-only; Minor GC applies safe fixes only from declared `SOURCES.md` contracts.
- Never delete memory/agent originals; archive or mark superseded only.
- Agent self-resolve honors `autonomy` policy + the `never_auto` code floor in `_common.py`.
- The human owns the boundary; the agent acts within it. Every resolution is logged.

## Dogfood requirement

Any new demo dir or runner script must be cited in `SOURCES.md` and listed in README.md.
`validate_context_gc.py` enforces this — a missing citation turns CI red.


始终用中文回答我

 当复杂的需求的时候可以选择使用  sequential-thinking MCP  
 Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

Tradeoff: These guidelines bias toward caution over speed. For trivial tasks, use judgment.

1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

State your assumptions explicitly. If uncertain, ask.
If multiple interpretations exist, present them - don't pick silently.
If a simpler approach exists, say so. Push back when warranted.
If something is unclear, stop. Name what's confusing. Ask.
2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

No features beyond what was asked.
No abstractions for single-use code.
No "flexibility" or "configurability" that wasn't requested.
No error handling for impossible scenarios.
If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:

Don't "improve" adjacent code, comments, or formatting.
Don't refactor things that aren't broken.
Match existing style, even if you'd do it differently.
If you notice unrelated dead code, mention it - don't delete it.
When your changes create orphans:

Remove imports/variables/functions that YOUR changes made unused.
Don't remove pre-existing dead code unless asked.
The test: Every changed line should trace directly to the user's request.

4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

"Add validation" → "Write tests for invalid inputs, then make them pass"
"Fix the bug" → "Write a test that reproduces it, then make it pass"
"Refactor X" → "Ensure tests pass before and after"
For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

These guidelines are working if: fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.