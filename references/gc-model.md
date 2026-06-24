# The mental model: context entropy IS garbage

Garbage collection is a solved problem in one domain (memory) and an unsolved mess in another (docs
& agent context). The concepts transfer directly. Internalize this mapping — every phase of the
skill is just a GC primitive applied to prose.

## The mapping

### Root
The **single source of truth** for a fact. GC starts from roots; so does drift control. A fact with
no root is already garbage-in-waiting — there is nothing to keep it true.
- **Docs:** the code / IaC / config the doc describes; the one canonical document; a schema/migration.
- **Agents:** `CLAUDE.md` / `SOUL.md` (the anchored "never drift" rules); the live config; the codebase.
- Industry names: *single source of truth (SSoT)*, *baseline*, *desired state*.

### Live / reachable
A statement is **live** if it traces to a root and still matches it. Live content is what you keep.
Reachability = "can I get from a root to this claim, and is it still consistent?"

### Garbage
Unreachable or inconsistent content: it contradicts its root, describes a reality that no longer
exists, points to something deleted, or duplicates a fact that lives authoritatively elsewhere.
Industry names: *drift*, *rot*, *staleness*.

### Mark
The diagnosis pass: find roots, trace each claim, flag the unreachable. **Read-only** — marking
never changes anything (just like GC mark doesn't free memory).

### Sweep
Reclaim the garbage: reconcile contradictions to the root, delete orphans, update stale claims. The
destructive pass — gated behind confirmation here, because unlike memory, a wrong free (deleting a
live doc) is expensive.

### Compaction
After sweeping, **consolidate**: one fact, one authoritative home; every other mention becomes a
pointer ("see X"), not a restatement. For agents, compaction also means **trimming context/memory**
— the literal industry use of the word ("compact before the session gets messy").

### Write barrier
In GC, a write barrier records mutations so the collector need not rescan everything. Here the
barrier is **`SOURCES.md`**: it records root→copy relationships so the next run re-checks only those
pairs. Cheap, incremental drift detection instead of a full re-read.

### Generational hypothesis
Most garbage is young: recently-touched areas drift most (code changed, doc lagged). When time is
limited, collect the "young generation" first — diff against recent git history and check the docs
near what changed.

### Leak
Entropy that is never collected: append-only knowledge bases, status files that only grow, agent
memory that accumulates. Leaks don't announce themselves — they slowly degrade trust and (for
agents) blow the context window. Schedule collection; don't wait for a crisis.

## Worked examples

**Doc drift (contradiction).** `CLAUDE.md` says "DeepSeek is the primary model"; the live
`config.yaml` says `MiniMax-M3`. The config is the root (it is what actually runs); the CLAUDE.md
line is garbage → reconcile to root.

**Config drift (copies diverge).** `config.yaml` exists locally and on the server; a migration
bumped the server's `_config_version` 27→29; the local copy is unchanged. Two copies, no declared
authority → the server (post-migration) is the root, local is stale → update + record the pair in
`SOURCES.md` so it is caught next time.

**Agent context rot.** A SOUL/skill set has accumulated three overlapping instructions about the
same behavior, one contradicting the other two, plus a reference to a skill that was deleted.
Garbage: the dead-skill reference (orphan) + the two losing instructions (duplicate/contradiction)
→ compact to one rule in the root (SOUL), sweep the rest.
