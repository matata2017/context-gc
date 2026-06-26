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
- **Mechanical trigger (not verdict):** `mark.py`'s `spec-drift-candidate` check reads SOURCES.md's
  declared root→copy pairs and, when a **code root** is git-newer than a **doc copy** that documents
  it, raises a `NEEDS_JUDGMENT` candidate — a prompt to go read both and judge, never an auto-verdict.
  This catches "the doc says X, the code now does Y" (e.g. the INSTALL.md hook-count drift), which the
  value/link/duplicate checks structurally cannot see. The mechanical half only *triggers* the
  judgment; the agent/human still decides whether it is real.
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

## Meta-drift — the authority map itself drifts (治理地图自身漂移)

The deepest blind spot: context-gc can only govern what `SOURCES.md` declares, but the map is written
once and silently goes stale as files are added. A governable doc that nobody declared is invisible to
every other check — it can rot freely. Symptom seen in practice: INSTALL_AGENT.md, install.py, and the
Chinese README each slipped through one at a time until someone *felt* the gap.

- **Coverage gap:** a top-level / onboarding file (README*, INSTALL*, CLAUDE.md, install.*) is not a
  root or copy in any SOURCES domain → `mark.py`'s `coverage-gap` check flags it `NEEDS_JUDGMENT`:
  *should this be governed, under which root?* A prompt to complete the map, not a verdict. The fix for
  "X wasn't detected" is not to patch X by hand (whack-a-mole) but to let undeclared files surface
  themselves. Narrow on purpose — only governable top-level docs, not internal demo/reference files.

## Drift axes the mechanical checks now trigger on (机械触发器，判断仍归人)

Each is a `NEEDS_JUDGMENT` trigger built from the SOURCES.md declaration — a prompt to go look, never
a verdict. They cover the axes a fact drifts along beyond simple value/link/duplicate:

- **stale-verification (TTL):** a domain's `Last verified` is older than ~120 days → the SYNCED claim
  has perished; re-run its Re-check and bump the date. *Old ≠ drifted, but it earns a re-look.*
- **orphaned-root (deletion):** a domain's root file was deleted → its copies govern nothing now.
  Promote a copy, remove the domain, or mark HISTORICAL.
- **implementation-gap (reverse spec-drift):** a DOC/spec root is git-newer than its CODE copy → the
  code may not yet implement the updated spec. The mirror of code-outpaces-doc; don't rewrite the spec down.
- **env-matrix-drift (environment axis):** 2+ per-environment config siblings (`config.dev`/`config.prod`)
  not declared FORK → is the divergence intentional (declare FORK) or accidental (reconcile)?
- **structural-drift (shape, not value):** a code root's public CLI flags are absent from its doc copy →
  the doc describes an older interface shape. Narrow to CLI flags on purpose — every value can be "right"
  yet the interface undocumented.
- **external-root-drift (root outside the repo):** a domain's root is a URL/API → local checks can never
  verify it; a permanent blind spot. Prompt to probe the upstream. context-gc stays zero-dependency and
  does NOT fetch it.
