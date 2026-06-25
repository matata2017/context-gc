# Expected entropy report — advanced agent drift

## Entropy report — examples/demo-agent-drift-advanced

Status legend: SYNCED | DRIFTED | NOT_CHECKED | FORK | HISTORICAL | UNKNOWN_ROOT

🔴 SEMANTIC-INSTRUCTION-CLUSTER  DRIFTED/UNKNOWN_ROOT  CLAUDE.md, SOUL.md, memory/scraping-policy.md  scraping policy says `5 req/s` in one anchor and `10 req/s` in another  → choose policy root

🟡 MEMORY-LEAK / BLOAT  NOT_CHECKED  memory/user-preference-2026-01.md, memory/user-preference-2026-02.md, memory/user-preference-2026-03.md  dated variants of one preference  → condense to one current memory

🟡 SKILL-BLOAT / DISTRACTION  NOT_CHECKED  skills/research/SKILL.md and skills/search/SKILL.md overlap on web search/source review  → review/freeze/split after confirmation

🟡 TONE-BEHAVIOR-DRIFT / CLASH  UNKNOWN_ROOT  CLAUDE.md says concise/direct while SOUL.md says warm/detailed step-by-step  → choose behavior root or scoped FORK

## session entropy report

🟠 STALE-PLAN-SIGNAL  UNKNOWN_ROOT  transcript.md  Plan A is later cancelled and Plan B supersedes it  → compact transcript

🟢 ORPHANED-SESSION-TASK  NOT_CHECKED  transcript.md  TODO implement Plan A remains after cancellation  → close or archive

🟢 TOOL-RESULT-BLOAT  NOT_CHECKED  transcript.md  tool output remains after result is settled  → replace with evidence pointer

## Sweep plan — apply? (y/n)

- `CLAUDE.md` / `SOUL.md`: keep one authoritative scraping limit and point other copies at it.
- `memory/`: merge dated user-preference variants into one current memory; preserve history only if useful.
- `skills/`: review overlapping search/research skills; freeze or split only after approval.
- `transcript.md`: create a compaction summary with durable decisions, unresolved questions, and evidence pointers. Do not silently delete evidence.
- `SOURCES.md`: add an `agent-context-policy` entry for the confirmed roots and exceptions.
