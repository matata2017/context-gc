---
name: context-gc
description: Garbage collection for documentation and AI-agent context — detects drift, staleness, contradictions, and duplication across docs/configs/READMEs/knowledge bases and agent instructions (SOUL/CLAUDE.md/memory), traces every fact to its authoritative source, then converges or sweeps the garbage and leaves a SOURCES.md so future drift is caught early. Use when docs are out of date, configs drifted (local vs prod), sources contradict each other, a knowledge base grew into a mess, or an agent's context/instructions rotted ("context rot"). Triggers include "docs are stale", "config drift", "this contradicts that", "clean up the docs", "gc the docs/knowledge base", "treat document or agent drift".
resources:
  - LOCAL_FS
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

> **Full mental model:** load `references/gc-model.md`.

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
- "Our config drifted — local vs server disagree"
- "These two docs / this doc and that comment contradict each other"
- "This knowledge base / CLAUDE.md / SOUL has grown into a mess"
- "Context rot" — an agent's instructions/memory accumulated stale, conflicting cruft
- Any "clean up / reconcile / find what's stale in" a body of docs or agent config

## The GC cycle — run **in order**, do not skip

### Phase 1 — MARK (diagnose) → produce an entropy report
1. **Scope the heap:** which files/dirs are in scope (docs, configs, agent files). Ask if unclear.
2. **Find the roots.** For each domain of facts, identify the ONE authoritative source (the
   code/config it describes, the canonical doc, git history). If authority is ambiguous,
   **ask the user — do not guess truth.**
3. **Trace reachability.** Check each notable claim against its root + cross-check against other
   docs. Walk `references/entropy-checklist.md` (the garbage types + how to detect each).
4. **Mark garbage**, severity-ranked → output the **entropy report** (format below). Stop here —
   marking is read-only.

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

## Safety rules — never corrupt the heap
1. **Never collect a live object.** Don't delete/rewrite anything you haven't confirmed is garbage.
   Unsure whether it's authoritative or stale? **Flag it, ask — don't sweep.**
2. **The user owns "truth."** When two sources conflict and the root is unclear, the skill
   *proposes*; the user decides which is authoritative.
3. **Confirm before write** (the Phase 2 gate). Marking is safe/read-only; sweeping is not.
4. **Prefer incremental over stop-the-world.** Collect one domain at a time; reserve a big sweep for
   explicit go-ahead.

## Output formats

**Entropy report (Phase 1):**
```
## Entropy report — <scope>
🔴 CONTRADICTION  <file:loc>  "<claim>"  ↔  root <root>: "<truth>"   → reconcile
🟠 STALE          <file:loc>  "<claim>"  — root <root> moved on       → update/delete
🟠 ORPHAN         <file:loc>  refers to <gone>  (not in root)         → delete/repoint
🟡 DUPLICATE      <fact> in <fileA>, <fileB>, <fileC>  — no authority → compact → <root>
🟢 BLOAT          <file/section>  redundant/overgrown                 → condense
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
