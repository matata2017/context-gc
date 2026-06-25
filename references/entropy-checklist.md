# Entropy checklist — the garbage taxonomy

The MARK pass walks this list. Each type has a **detection method** and a **severity**. Output every
finding as `severity  type  file:line  "claim"  → root/treatment`. Explain *why*; cite evidence.

> Reviewer discipline: report **why**, not just **what**. "Stale: README:12 says port 8000 but
> docker-compose.yml:9 maps 8080" beats "README looks outdated."

## 🔴 Critical — actively misleading

### 1. Contradiction (矛盾)
Two sources assert different things about the same fact; or a doc contradicts its code/config root.
- **Detect:** cross-reference the same fact across files; diff doc claims against the live root
  (code, config, schema). Watch numbers, names, versions, ports, flags, model names, paths.
- **Why critical:** a reader cannot tell which is true → acts on the wrong one.

### 2. Wrong (错 — silent staleness)
A claim that is simply false against the root, and *not* contradicted by another doc — so it hides.
- **Detect:** verify load-bearing claims directly against the root — does this flag / endpoint /
  field still exist and behave as described?
- **Why critical:** invisible to cross-referencing; only a root check catches it.

## 🟠 High — broken reachability

### 3. Spec / SDD drift (规格漂移)
An SDD/spec/design document was once authoritative, but later requirement changes, code edits, tests,
or config changes moved the implementation away from it.
- **Detect:** compare load-bearing spec claims against current code, tests, config, API schemas, and
  latest decision docs. Watch words like "must", "shall", "current", "planned", and "future".
- **Why high:** agents often treat SDD as root context. A stale spec can pull future edits back
  toward an obsolete design.
- **Root decision:** do not automatically let code win. Classify the claim as current fact, future
  intent, historical record, or unknown authority.

### 4. Stale (陈旧)
Describes a past reality; the root has moved on (renamed, restructured, re-scoped).
- **Detect:** git recency — is the doc older than the code it describes? Did a referenced
  module/flow change shape? (Generational: check recently-changed areas first.)

### 5. Orphan / dangling (孤儿/悬挂)
References something that no longer exists: a deleted file, a removed flag, a dead link, a renamed
function, a retired endpoint.
- **Detect:** resolve every reference against the current tree — does the target still exist?

## 🟡 Medium — duplication (the drift factory)

### 6. Duplication (重复)
The same fact stated authoritatively in N places. Today they agree; tomorrow someone edits one.
**Every duplicate is a future contradiction.**
- **Detect:** find facts repeated across files (install steps, config values, architecture claims,
  port numbers, model names). N copies, no single declared owner.
- **Treat:** pick the root, leave a pointer in the others (see treatment-playbook).

## 🟢 Low — bloat & rot

### 7. Bloat / rot (膨胀/腐烂)
Verbose, redundant, disorganized, append-only growth. Not wrong, but it lowers signal and hides the
critical stuff. For agents this is **context-window pressure**.
- **Detect:** sections that restate each other; ever-growing logs/status files; "we tried X, then Y,
  then Z" archaeology that should be one current statement.

## Status model (borrowed from configuration drift tools)

Use a status code alongside severity so reports are machine-readable:

- `SYNCED` — checked against root and currently matches.
- `DRIFTED` — checked against root and differs.
- `NOT_CHECKED` — not checked because the root/tool/scope cannot verify it yet.
- `UNKNOWN_ROOT` — the claim may be true, but no authority has been established.
- `FORK` — intentionally diverges from root; document the exception in `SOURCES.md` and do not keep re-flagging it.
- `HISTORICAL` — accurately records a past state (ADR, changelog, incident report, release note);
  preserve or archive rather than reconciling it to the current root.


## Agent-specific (智能体漂移 / context rot)

Use this four-part context-rot taxonomy when the heap is an agent's own context:

- **Poisoning** — false summaries, hallucinated state, or wrong memories that future steps repeatedly reuse.
- **Distraction** — too much irrelevant history/tool output causing the model to repeat old actions or lose the current goal.
- **Confusion** — too many overlapping tool definitions, skills, or instructions; the model chooses the wrong one.
- **Clash** — mutually incompatible instructions or facts in SOUL/CLAUDE.md/memory/session context.

When the heap is an agent's own config (SOUL / CLAUDE.md / skills / memory), all of the above apply,
plus:
- **Stale instruction:** a rule describing a tool/flow that has since changed → 🟠.
- **Conflicting instruction:** two rules that cannot both hold → 🔴 (the agent obeys unpredictably).
- **Semantic duplicate:** the same policy restated with different wording or values across context layers → 🟡/🔴.
- **Dead skill / memory:** references a removed skill, or memory facts now false → 🟠 orphan.
- **Memory leak:** append-only memory/journal never compacted → 🟢 bloat → context rot.
- **Skill/tool bloat:** too many overlapping or oversized skills compete for attention → 🟢/🟡 distraction.
- **Tone / behavior drift:** concise vs verbose, warm vs blunt, or step-by-step vs no-explanation rules clash → 🟡/🔴.
- **Anchor check:** are the "never drift" rules actually in the root (CLAUDE.md/SOUL), or scattered
  across places that will drift? Scattered anchors → consolidate in Phase 2.

### Memory layers (长期 / 中期记忆 / 画像)

Agents keep layered memory that drifts independently. Classify by layer before treating it:

- **Long-term:** stable user/project facts and durable preferences → one canonical current memory + evidence.
- **Mid-term:** active project/session state and temporary goals → expire/archive when the task is done or cancelled.
- **Profile:** user/agent traits and preferences → reconcile against long/mid-term memory; surface conflicts, don't auto-overwrite.
- **Historical / superseded:** old memory kept for audit → preserve, mark `status: superseded`, do not silently delete.

Memory drift findings (`scripts/mark.py`):
- **memory-conflict:** one subject holds incompatible values (concise vs verbose, old vs new tool) → `UNKNOWN_ROOT`, review.
- **memory-superseded-chain:** dated variants or `supersedes` chains should compact to one current memory.
- **profile-drift:** profile disagrees with long/mid-term memory → reconcile or scope.
- **midterm-expired:** mid-term memory references a completed/cancelled plan → archive/mark superseded.
- **memory-budget:** memory heap too large for active context → compact.

Memory drift is **never** auto-deleted. `memory-condense` (Minor GC) only writes a current canonical memory
from a declared contract, preserves originals as evidence, and escalates ambiguous conflicts as
`CONFLICT_NEEDS_REVIEW`.

## Session heap (单会话上下文腐烂)

A long-running conversation is also a heap. MARK exported transcripts or summaries when the agent keeps
repeating itself, follows an old plan, or carries huge tool output forward.

- **Stale plan:** an earlier plan was superseded by a later user decision → mark old plan as garbage, preserve latest decision.
- **Orphaned task:** TODO/follow-up remains in context after completion or abandonment → close or move to durable memory.
- **Repeated decision:** the same settled fact appears across many turns → compact to one durable statement.
- **Tool-output bloat:** large command/log output remains after its result is settled → replace with pointer + one-line outcome.
- **Session budget pressure:** transcript dominates useful context → compact transcript, preserving evidence and unresolved questions.
