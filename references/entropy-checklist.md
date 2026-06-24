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

### 3. Stale (陈旧)
Describes a past reality; the root has moved on (renamed, restructured, re-scoped).
- **Detect:** git recency — is the doc older than the code it describes? Did a referenced
  module/flow change shape? (Generational: check recently-changed areas first.)

### 4. Orphan / dangling (孤儿/悬挂)
References something that no longer exists: a deleted file, a removed flag, a dead link, a renamed
function, a retired endpoint.
- **Detect:** resolve every reference against the current tree — does the target still exist?

## 🟡 Medium — duplication (the drift factory)

### 5. Duplication (重复)
The same fact stated authoritatively in N places. Today they agree; tomorrow someone edits one.
**Every duplicate is a future contradiction.**
- **Detect:** find facts repeated across files (install steps, config values, architecture claims,
  port numbers, model names). N copies, no single declared owner.
- **Treat:** pick the root, leave a pointer in the others (see treatment-playbook).

## 🟢 Low — bloat & rot

### 6. Bloat / rot (膨胀/腐烂)
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
- **Dead skill / memory:** references a removed skill, or memory facts now false → 🟠 orphan.
- **Memory leak:** append-only memory/journal never compacted → 🟢 bloat → context rot.
- **Anchor check:** are the "never drift" rules actually in the root (CLAUDE.md/SOUL), or scattered
  across places that will drift? Scattered anchors → consolidate in Phase 2.
