---
name: context-gc
description: Garbage-collect docs, SDD/specs, configs, KBs, and agent context. Use when docs/specs drift from code after requirement changes, configs contradict, KBs duplicate/bloat, or CLAUDE.md/SOUL/memory has context rot.
---

# context-gc — Garbage Collection for Docs & Agent Context

Documentation, configs, knowledge bases, and agent instructions **rot**: code changes and the doc
doesn't; the same fact is copied to five places and they drift apart; local config diverges from
production; a status file is stale the moment it's written; a knowledge base grows until no one
knows which line is true. This is **entropy** — and the cure is not "rewrite the docs once." It's a
**garbage-collection discipline** you can run again and again.

The metaphor is structurally exact, not decorative: the industry already calls the fix "single
source of truth" (= GC **roots**), "baseline" (= the **live set**), "drift" (= **garbage**), and even
"compaction" (the literal GC term, reused for trimming agent context). context-gc makes that mapping
explicit and operational.

> **Progressive loading:** read `references/gc-model.md` only when the user asks about the metaphor/design; read `references/entropy-checklist.md` during MARK; read `references/treatment-playbook.md` during SWEEP; read `references/hooks.md` only when installing or changing hooks.

| GC concept | Context entropy |
|---|---|
| **Root** | The authoritative source of a fact (the code/IaC, the canonical doc, CLAUDE.md/SOUL) |
| **Live / reachable** | A statement that traces to a root and still matches it |
| **Garbage** | Stale, orphaned, contradictory, or duplicated content with no living root |
| **Mark** | Find the roots, trace each claim, flag what's unreachable |
| **Sweep** | Reconcile / delete / converge the garbage |
| **Compaction** | Dedupe to one authority; trim agent context/memory |
| **Write barrier** | `SOURCES.md` — the authority map that catches future drift cheaply |

## When to use
- "The docs say X but the code does Y" / "the README is out of date"
- "The SDD/spec was true when written, but requirements changed and the code no longer matches"
- "Our config drifted — local vs server disagree"
- "These two docs / this doc and that comment contradict each other"
- "This knowledge base / CLAUDE.md / SOUL has grown into a mess"
- "Context rot" — an agent's instructions/memory accumulated stale, conflicting cruft
- "Agent drift" — CLAUDE.md/SOUL/skills/memory/session context disagree, bloat, or change behavior
- Any "clean up / reconcile / find what's stale in" a body of docs or agent config

## Managed mode — agent-first, human fallback

context-gc is designed for an agent-first world: the **loop/agent** drives it, resolves the drift it
is *allowed* to, and escalates only what policy reserves for a human. The human **sets the policy**
once and audits the trail; they no longer have to operate the tool every time.

A single non-interactive tick is the default interface:

```bash
python scripts/gc_tick.py --target .            # print structured TickResult JSON
python scripts/gc_tick.py --target . --quiet    # one-line summary
```

`gc_tick` chains `mark → minor_gc → review_queue → resolve --auto`. It never blocks. Pending
escalations accumulate in `.context-gc/review-queue.json`; agent resolutions append to
`.context-gc/decisions.jsonl` with evidence and reversibility.

### Autonomy policy (configurable boundary)

`.context-gc/config.yml` contains the `autonomy:` block:

```yaml
autonomy:
  level: assist            # off | assist | auto | full
  agent_may_resolve:
    - safe-mechanical      # scalar-sync ports, pointer-copy, generated-state
  min_recommend_confidence: 0.0
  never_auto:
    - protected
    - delete
    - memory-condense
    - unknown-root
```

Levels:
- `off` — agent resolves nothing; everything queues.
- `assist` (default) — resolves `safe-mechanical` items with `recommend >= 0`.
- `auto` — additionally resolves kinds listed in `agent_may_resolve`.
- `full` — resolves everything **except** `never_auto`, which is a code-level hard floor.

Even `level: full` cannot override `never_auto`: protected roots, delete operations,
memory-condense, and genuinely ambiguous items (`recommend == -1`) always escalate.

### When an agent is driving

Loop / agent orchestrator should:
1. Run `gc_tick` after meaningful work or on a schedule.
2. If `escalated > 0` or `steps_rc` non-zero: inspect `review-queue.json`. An escalated item is one
   policy reserves for a human (protected root, `unknown-root`, delete, memory). Your **only** legal
   moves on it are: leave it queued, report it to a human, or spawn a higher-authority worker if your
   framework has one. Do **not** resolve it yourself, and do **not** reach past the tool to hand-edit
   `SOURCES.md`.
3. If `pending == 0`: continue; no human interruption needed.
4. After a tick, write the durable outcome back into your own long-term memory (whatever your framework
   uses): which domains you auto-resolved, which you escalated, the current `SOURCES.md` status.
   `gc_tick`'s JSON and `.context-gc/decisions.jsonl` are that hand-off surface — context-gc records the
   audit trail but cannot reach into your memory. A later session only knows this skill was already
   calibrated if you wrote that there; otherwise it re-derives stale state from the day it was installed.

> **Escalation is a HOLD, not a cue to freestyle.** A capable agent's instinct is to "finish" an open
> item by picking an option — that instinct is wrong here. Items are escalated *because* the root is
> protected or genuinely ambiguous, so you do not have the authority to pick. Above all, never use
> **`mark_fork` / `mark_historical` as a default to clear the queue** — both set a `SOURCES.md` status
> that *stops the item from ever being re-flagged*. Marking a real contradiction (e.g. two different
> rate limits) as FORK does not resolve it, it **silences** it. `mark_fork` is correct only once the
> divergence is *confirmed* intentional. When unsure: HOLD. A pending item waiting for a human is the
> right outcome, not a failure to act.

### Human fallback — `setup` and `review`

When a human is present or policy escalates, use the interactive workflows below. They follow the
same split: deterministic scripts produce machine-readable artifacts, and **you (the SKILL) own all
interaction via AskUserQuestion** — scripts never ask and never decide truth.

#### `setup` — install → managed in a few questions

When the user says "set up context-gc" / "manage drift here" / `/context-gc setup`:

1. Run `python scripts/init_context_gc.py --target . --guided`. It scans, profiles, writes the
   `SOURCES.md` skeleton + safe-default `config.yml`, and emits `.context-gc/setup-draft.json`.
2. Read `setup-draft.json`. For each domain with `"needs_question": true` (ambiguous root), ask the
   user **one AskUserQuestion**: "Which is the authoritative source for `<domain>`?" with the
   `candidate_roots` as options. Write the confirmed root into `SOURCES.md`. Never guess.
3. Ask the draft's single `authorization_question`: may context-gc auto-fix mechanical low-risk drift
   (ports/pointers) in the background without asking each time? On "Yes", set `minor_gc.apply_safe:
   true` in `config.yml` (scalar/pointer only — sensitive agent/memory fixes stay review-only no
   matter what). On "No", leave it `false` (everything queues for review).
4. Offer to install the hooks from `examples/claude-settings-hooks.json` (PostToolUse dirty-card,
   Stop reminder, optional PreToolUse guard).
5. Tell the user: drift is now managed; the agent will handle what it can and surface decisions when
   they're needed.

Safe defaults mean "watching" is free from the start: `auto_mark.enabled: true` (read-only) and
`minor_gc.enabled: true` with `apply_safe: false` — it detects and queues, but never auto-edits until
the user authorizes it once in step 3.

#### `review` — resolve waiting decisions as quick choices

When the user says "review drift" / `/context-gc review`, or the Stop hook reported "N drift decisions
waiting":

1. Run `python scripts/review_queue.py --target .` to aggregate open `NEEDS_REVIEW` /
   `CONFLICT_NEEDS_REVIEW` / `UNKNOWN_ROOT` decisions into `.context-gc/review-queue.json`.
2. For each `"status": "open"` item, ask **one AskUserQuestion** built from the item: use `summary`
   as the question, `evidence` for context, and the item's `options` as the choices (put the
   `recommend` index first if it is ≥ 0; if `recommend` is -1 the conflict is genuinely ambiguous —
   present options neutrally).
3. On the user's answer, perform the option's declarative `action`:
   - `set_current_memory` → write the chosen source as the current memory (keep originals as evidence).
   - `consolidate_anchor` → keep the policy in the chosen root, replace the other copies with pointers.
   - `mark_fork` / `mark_historical` → set that domain's `SOURCES.md` status; stop re-flagging it.
   - `reconcile_to_root` / `flag_implementation_gap` → apply the SDD-drift treatment from the playbook.
   - `manual` / `defer` → let the user edit, or leave the item for later.
4. Update `SOURCES.md` for the resolved domain and remove the item from the queue.
5. Batch-friendly: 3 waiting decisions = 3 quick questions, then done. All existing safety rules still
   hold — confirmation **is** the user's answer; never delete memory/evidence to satisfy a choice.

## The GC cycle — run **in order**, do not skip

### Phase 0 — INIT (once per repo) → bootstrap the write barrier
First time on a repo, establish the root map instead of re-deriving scope by hand every run:
```
python scripts/init_context_gc.py --target .
```
This scans context-bearing files, proposes fact domains, and writes a `SOURCES.md` skeleton (status
`NOT_CHECKED`) plus `.context-gc/config.yml`. **init proposes roots; it never decides truth** — walk
the skeleton with the user and confirm or replace each root. Skip this phase if `SOURCES.md` exists.

### Phase 1 — MARK (diagnose) → produce an entropy report
MARK has two halves. Run the mechanical half first, then apply judgment.

1. **Mechanical (deterministic, scripted):**
   ```
   python scripts/mark.py --target .
   ```
   This emits drift *candidates* — orphan references, cross-file duplicate blocks, stale docs — to
   `.context-gc/findings.json` and a terse report. It never edits. Use it so you spend tokens on
   decisions, not grep.
2. **Scope the heap:** confirm which files/dirs are in scope (from `SOURCES.md` + config). Ask if unclear.
3. **Find the roots.** For each domain, identify the ONE authoritative source (code/config it
   describes, the canonical doc, git history). Roots can be external (an API, a server) — probe them.
   If authority is ambiguous, **ask the user — do not guess truth.**
4. **Judgment:** for each candidate, decide is-it-garbage, which is root, and FORK vs HISTORICAL.
   Cross-check claims against roots and walk `references/entropy-checklist.md` for types the
   mechanical pass can't catch (contradictions, wrong-but-uncontradicted, agent context rot).
5. **Mark garbage**, severity-ranked → output the **entropy report** (format below). Marking is read-only.

### Phase 2 — SWEEP (treat) → **confirm before writing**
1. For each marked item, choose the treatment from `references/treatment-playbook.md`
   (reconcile-to-root / delete-orphan / compact-duplicate / condense-bloat).
2. **HARD GATE:** present the **sweep plan** (every file that will change + the change) and get
   explicit user confirmation. **No edits before confirmation.**
3. Apply only confirmed changes. Restate the fact authoritatively in the surviving copy; replace
   duplicates with a pointer to the root.

### Phase 3 — BARRIER (prevent future drift)
1. Write/update **`SOURCES.md`** from `templates/SOURCES.md.template`: the authority map (root set)
   — for each fact-domain, its root, the derived copies that must match, and a re-check command.
2. This is the **write barrier**: the next run reads SOURCES.md and re-checks only the declared
   root→copy pairs — fast incremental GC instead of a full re-scan.
3. Optional but recommended: install the hook recipes in `references/hooks.md` so context-bearing
   file edits create dirty cards in `.context-gc/dirty.jsonl` and trigger an end-of-session reminder.
   Hooks may run quiet auto-MARK after a configured dirty-card threshold. For automated agents,
   **Minor GC** may also run after a threshold and apply only pre-authorized safe fixers declared in
   `SOURCES.md`. Hooks must never choose authority, edit protected context, or sweep unknown-root drift.

## Safety rules — never corrupt the heap
1. **Never collect a live object.** Don't delete/rewrite anything you haven't confirmed is garbage.
   Unsure whether it's authoritative or stale? **Flag it, ask — don't sweep.**
2. **The user owns "truth."** When two sources conflict and the root is unclear, the skill
   *proposes*; the user decides which is authoritative.
3. **Confirm before write** (the Phase 2 gate). Marking is safe/read-only; sweeping is not.
4. **Prefer incremental over stop-the-world.** Collect one domain at a time; reserve a big sweep for
   explicit go-ahead.
5. **Automation boundary:** hooks and scripts may mark, score, summarize, and write `.context-gc/`
   reports. Minor GC may auto-apply only pre-authorized safe fixers (`scalar-sync`, `pointer-copy`,
   generated-state cleanup, `memory-condense`) declared in `SOURCES.md`; protected files,
   `UNKNOWN_ROOT`, `FORK`, and `HISTORICAL` domains remain report-only. `memory-condense` never
   deletes memory evidence and escalates ambiguous memory conflicts as `CONFLICT_NEEDS_REVIEW`.

## Output formats

**Entropy report (Phase 1):**
```
## Entropy report — <scope>
Status legend: SYNCED | DRIFTED | NOT_CHECKED | FORK | HISTORICAL | UNKNOWN_ROOT
🔴 CONTRADICTION  DRIFTED       <file:loc>  "<claim>"  ↔  root <root>: "<truth>"   → reconcile
🟠 STALE          DRIFTED       <file:loc>  "<claim>"  — root <root> moved on       → update/delete
🟠 SPEC_DRIFT     UNKNOWN_ROOT  <spec:loc> describes X, code/tests do Y             → decide root
🟠 ORPHAN         DRIFTED       <file:loc>  refers to <gone>  (not in root)         → delete/repoint
🟡 DUPLICATE      UNKNOWN_ROOT  <fact> in <fileA>, <fileB>, <fileC>  — no authority → compact → <root>
🟢 BLOAT          NOT_CHECKED   <file/section>  redundant/overgrown                 → condense
⚪ FORK           FORK          <file:loc> intentionally diverges from root          → document exception
⚪ HISTORICAL     HISTORICAL    <file:loc> accurately records past state             → preserve/archive
Roots used: <list>.   Ambiguous authority (need your call): <list>.
```

**Sweep plan (Phase 2, before any edit):**
```
## Sweep plan — apply? (y/n)
<file>:  <what changes>   (reason: <garbage type> → <treatment>)
...
New/updated: SOURCES.md (authority map)
```

Keep reports terse and evidence-bearing — cite `file:line` and the root, and explain **why** it's
garbage, not just **what**. Reviewer discipline: severity + "why", never a vague "looks outdated."

For SDD/spec drift, do not assume code always wins. Classify each claim first:

- **Current fact:** code/tests/config/IaC are usually the root; update the spec to match reality.
- **Future intent:** the latest product decision/spec is the root; flag code as not yet implemented.
- **Historical decision:** preserve as `HISTORICAL`; add a superseded pointer instead of rewriting history.
- **Unknown authority:** mark `UNKNOWN_ROOT` and ask whether to update docs to code or code to spec.

For agent drift, classify the heap before treating it:

- **Poisoning:** false memory/summary/tool fact that would be reused → correct or delete only after root confirmation.
- **Distraction:** skills, memory, or session transcript exceed useful context budget → condense or archive with evidence pointers.
- **Confusion:** near-duplicate instructions across CLAUDE.md/SOUL/skills/memory disagree subtly → pick one anchor root.
- **Clash:** mutually incompatible behavior/tone/tool rules → ask which policy wins.
- **Session rot:** transcript contains superseded plans, orphaned TODOs, repeated decisions, or tool-output bloat → summarize durable decisions + unresolved questions; never silently drop evidence.
- **Memory drift:** long-term, mid-term, and profile memory layers conflict or pile up dated variants → condense to one current memory + evidence list; reconcile profile conflicts by review; mark expired mid-term memory `superseded`; never delete originals silently.
