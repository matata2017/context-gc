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

## Compaction (after sweeping)
- **Dedupe across the whole scope:** one fact, one authoritative home. Every other mention is a
  one-liner + pointer.
- **For agents:** trim context — condense SOUL, consolidate skills, compact memory into gbrain pages.
  The goal is to reduce the effective "heap size" the agent carries.
- **SOURCES.md update:** record every root→copy pair discovered during this GC run.