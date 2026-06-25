# Expected sweep plan — advanced agent drift

## Sweep plan — apply? (y/n)

Files to change after confirmation only:

1. `CLAUDE.md` / `SOUL.md`
   - Choose the authoritative scraping policy (`5 req/s` vs `10 req/s`).
   - Choose the behavior root (concise/direct vs warm/detailed) or document scoped FORK exceptions.

2. `memory/`
   - Condense the three dated user preference files into one durable current fact.
   - Preserve historical reason only if it matters for future behavior.

3. `skills/`
   - Review overlapping `search` and `research` skills.
   - Freeze, merge, or split only after explicit approval.

4. Session transcript
   - Summarize Plan B as the current decision.
   - Close or archive the Plan A TODO.
   - Replace large settled tool output with a pointer/evidence summary.

5. `SOURCES.md`
   - Add `agent-context-policy`, `agent-memory`, `active-skills`, and `session-context` authority entries.

Do not auto-sweep. MARK and session MARK are read-only.
