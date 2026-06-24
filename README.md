# context-gc

> Garbage collection for docs & agent context — detects drift, staleness, contradictions,
> duplication, and context rot; traces every fact to its authoritative source; then converges or
> sweeps the garbage and leaves a `SOURCES.md` so future drift is caught early.

```
┌───────────┐    ┌───────────┐    ┌───────────┐
│  MARK     │ →  │  SWEEP    │ →  │  BARRIER  │
│ (diagnose)│    │ (treat)   │    │ (prevent  │
│           │    │→ confirm  │    │  future)  │
│ read-only │    │  before   │    │           │
│           │    │  write    │    │SOURCES.md │
└───────────┘    └───────────┘    └───────────┘
```

## The problem

Documentation, configs, knowledge bases, and AI-agent instructions rot:
- Code changes and the doc doesn't
- The same fact is copied to five places and they drift apart
- Local config diverges from production
- A status file is stale the moment it's written
- Agent context (SOUL/CLAUDE.md/memory) accumulates dead, contradictory cruft = **context rot**
- Knowledge bases grow until no one knows which line is true

## The approach: treat it as garbage collection

The metaphor is structurally exact, not decorative — GC concepts map 1:1:

| GC | Context entropy |
|---|---|
| Root | The authoritative source of a fact (code/config/CLAUDE.md) |
| Live/reachable | A statement that traces to a root and matches it |
| Garbage | Stale, orphaned, contradictory, duplicated content |
| Mark | Find roots → trace claims → flag garbage (read-only) |
| Sweep | Reconcile/delete/compact the garbage (gated by confirmation) |
| Compaction | Dedupe to one authority; trim agent context |
| Write barrier | `SOURCES.md` — authority map for cheap re-check next time |

Full mental model: [`references/gc-model.md`](references/gc-model.md)

## What it covers

- **Docs & READMEs** — stale, contradictory, or orphaned claims
- **Configs** — local↔server drift, masked configs, fork-noted divergence
- **Knowledge bases** — bloat, duplication, ever-growing append-only decay
- **Agent context** — SOUL/CLAUDE.md/skills/memory context rot (stale instructions, conflicting rules, dead references, memory leak)
- **A single session** — context rot within a long-running conversation

## Usage (as a Claude Code skill)

Install this directory as a Claude skill (or copy it into your Claude skills directory). The skill triggers on tasks like stale docs, config drift, contradictory sources, knowledge-base bloat, or agent context rot.

Then when you say anything like:
- "The docs are stale / out of date"
- "Config drifted" / "this contradicts that"
- "Clean up the docs" / "gc the knowledge base"
- "My agent feels dumber than before" / "context rot"
- "Treat documentation drift"

Claude runs the **3-phase GC cycle**:
1. **MARK** — scopes the heap, finds roots, traces each claim, outputs an entropy report
2. **SWEEP** — presents a sweep plan for confirmation, then applies treatments
3. **BARRIER** — writes/updates `SOURCES.md` (authority map for cheaper future runs)

Optional hook integration turns this into an incremental GC: `PostToolUse` records dirty context
files and `Stop` reminds you to run MARK before entropy accumulates. See
[`references/hooks.md`](references/hooks.md) and
[`examples/claude-settings-hooks.json`](examples/claude-settings-hooks.json).

Read the full skill: [`SKILL.md`](SKILL.md)

## Files

```
context-gc/
├── SKILL.md                         # Full skill — GC cycle, safety rules, output formats
├── README.md                        # This file
├── LICENSE
├── references/
│   ├── gc-model.md                  # GC ↔ entropy mental model (must read once)
│   ├── entropy-checklist.md         # Garbage taxonomy + detection methods
│   ├── treatment-playbook.md        # Per-type sweep actions
│   └── hooks.md                     # Optional Claude Code hook recipes
├── scripts/
│   └── context_gc_hook.py           # Hook helper: dirty cards + stop reminder
├── examples/
│   └── claude-settings-hooks.json   # Example .claude/settings.json hook config
└── templates/
    └── SOURCES.md.template          # Authority map template (the write barrier)
```

## Development

```
# Run a GC walk on the repo itself (eat your own dog food)
  1. Run the MARK phase on this repo
  2. Inspect the entropy report
  3. Run SWEEP (with confirmation)
```

## License

MIT — fork, remix, dogfood, contribute.

## See also

- [LogRocket: Context rot is slowing down your AI agent](https://blog.logrocket.com/context-rot-slowing-down-your-ai-agent-how-fix/)
- [MindStudio: What is context rot and how do you prevent it?](https://www.mindstudio.ai/blog/what-is-context-rot-ai-agents)
- [Josys: Configuration drift lifecycle](https://josys.com/article/understanding-the-lifecycle-of-configuration-drift-detection-remediation-and-prevention)
- [Computhink: SSoT in document governance](https://computhink.com/blog/why-a-single-source-of-truth-is-critical-for-enterprise-document-governance/)