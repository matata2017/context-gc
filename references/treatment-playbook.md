# Treatment playbook — per-garbage-type sweep actions

For each garbage type in the entropy report, pick the treatment below.

## 🔴 Contradiction

| Sub-type | Treatment | Notes |
|---|---|---|
| Doc says X ↔ code/config does Y | **Reconcile to root.** Restate the truth as it stands in the root. Delete the old claim; do not leave a comment that it "used to be" unless the history matters. | **The root always wins.** If you aren't sure which is root, ask. |
| Doc A says X ↔ Doc B says Y | **Establish authority.** The user decides which doc is canonical. Sweep the other to match + record the pair in SOURCES.md. | If both are non-canonical, converge to one and mark the other as a pointer. |

## 🔴 Wrong (silent staleness)
| Treatment | Notes |
|---|---|
| **Replace with truth from root.** Verify the load-bearing claim against the live code/config; write the correct version. | If the claim is unrecoverable (the described feature is gone), delete it. |

## 🟠 Spec / SDD drift
| Claim type | Treatment | Notes |
|---|---|---|
| Current fact | **Update spec to actual behavior.** Treat code/tests/config/IaC as the root and rewrite the SDD/current spec to match. | Record the root→copy relationship in `SOURCES.md` so future requirement changes re-check the pair. |
| Future intent | **Keep spec as desired state; mark code as not implemented.** Add an implementation gap/TODO/issue instead of rewriting the spec to match incomplete code. | Ask the user before creating or editing task trackers. |
| Historical decision | **Preserve as history.** Mark `HISTORICAL` and add a superseded pointer to the current spec or ADR if needed. | Do not erase old rationale just because current behavior changed. |
| Unknown authority | **Ask which side wins.** Present both roots and stop before SWEEP. | This is the common SDD failure mode after requirement changes. |

## 🟠 Stale
| Treatment | Notes |
|---|---|
| **Update to match current root.** If the section describes v1 of a flow and v2 exists, rewrite to describe v2. | If the change is small (number/port/name), a direct edit is fine. If the change is structural, suggest a re-read of the root. |
| **Delete** if the described feature no longer exists. | No "formerly..." tombstone unless the user explicitly wants it. |

## 🟠 Orphan
| Treatment | Notes |
|---|---|
| **Re-point** to the renamed/new home if it still exists. | Use `git log --follow` or grep to find the move. |
| **Delete or strike** if the referenced entity is gone. | For agent config: delete the instruction referencing a dead skill/memory. |

## 🟡 Duplicate
| Treatment | Notes |
|---|---|
| **Compact to one authority.** Pick the canonical copy (ask user if ambiguity). In the others, replace the fact with: `> See [SOURCES.md#fact-name](path/to/root)` + a brief one-liner. | This is the most important treatment — prevents future contradiction. |
| If no copy is authoritative, converge them all to one agreed fact and designate a root. | |

## 🟢 Bloat / rot
| Treatment | Notes |
|---|---|
| **Condense.** Restate the signal in 1/3 the space. Remove "we tried X then Y then Z" archaeology; keep the current truth only. | For agent context: trim memory, compact overlapping instructions. |
| **Reorganize.** Split into logical sections, add table of contents. | Not required for every run — only when the entropy report flags. |

## ⚪ Historical
| Treatment | Notes |
|---|---|
| **Preserve as history.** Do not rewrite an ADR, changelog, incident report, or release note just because the current root changed. | Add a short status line or pointer to the current root if readers may confuse history for current instructions. |
| **Archive** if the historical material is cluttering operational docs. | Keep the historical record reachable; do not collect it as garbage unless the user confirms it has no value. |

## Agent-context compaction

| Drift type | Treatment | Notes |
|---|---|---|
| Semantic duplicate / confusion | **Consolidate to one anchor.** Keep the winning rule in CLAUDE.md/SOUL or the canonical skill; replace other copies with pointers. | Ask which policy wins when values differ. |
| Dead skill / memory | **Repoint or archive.** Replace with the confirmed successor or remove the instruction after approval. | Do not infer a successor from name similarity alone. |
| Memory leak | **Condense into durable facts.** Merge dated variants into current truth + historical note only when useful. | Preserve why a memory changed if it affects future behavior. |
| Skill/tool bloat | **Freeze/archive after review.** Move rarely used or overlapping skills out of active context only with confirmation. | Oversized skills can be split into progressive references. |
| Tone / behavior clash | **Pick one behavior root.** Keep the canonical style rule and delete/point exceptions. | Tone forks are valid if scoped by domain; mark `FORK`. |
| Session rot | **Compact transcript.** Summarize durable decisions, unresolved questions, and evidence pointers; discard repeated explanation only after summary. | Never silently drop tool evidence needed for audit/debugging. |

## Memory-layer cleanup (`memory-condense`)

| Layer | Treatment | Notes |
|---|---|---|
| Long-term variants | **Condense to one current memory** with an evidence list pointing at originals. | Declare a `memory-condense` contract in `SOURCES.md` with `Memory target`; auto-write runs only when `memory_gc.enabled` + `apply_safe`. |
| Mid-term expired | **Archive or mark `status: superseded`** once the task is done/cancelled. | Keep it reachable; do not delete active mid-term state. |
| Profile drift | **Reconcile, don't overwrite.** Surface profile vs preference conflicts for review. | Profile and preference can legitimately differ by context; scope as `FORK` if intentional. |
| Ambiguous conflict | **Escalate `CONFLICT_NEEDS_REVIEW`.** Write a candidate summary, never auto-resolve. | Equally-recent contradictory memories need a human/agent decision. |
| Identity / credentials / legal | **Report-only.** Listed in `memory_gc.protected_subjects`. | Never auto-condense sensitive memory. |

Memory rules: never delete originals silently; archive only when `memory_gc.allow_archive: true`; the
canonical memory comes from the declared **Root** and lists every source as evidence.

- **Dedupe across the whole scope:** one fact, one authoritative home. Every other mention is a
  one-liner + pointer.
- **For agents:** trim context — condense SOUL, consolidate skills, compact memory into gbrain pages.
  The goal is to reduce the effective "heap size" the agent carries.
- **SOURCES.md update:** record every root→copy pair discovered during this GC run.
