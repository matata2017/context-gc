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

## Quickstart

1. **Install**: see [`INSTALL.md`](INSTALL.md) — or just tell your agent "install context-gc"
2. **Read the skill**: [`SKILL.md`](SKILL.md)
3. **Try a demo**:
   - [`examples/demo-doc-vs-config/`](examples/demo-doc-vs-config/) — README says port 8000, compose says 8080
   - [`examples/demo-sdd-drift/`](examples/demo-sdd-drift/) — SDD says password login, code/tests use OAuth device flow
   - [`examples/demo-agent-context-rot/`](examples/demo-agent-context-rot/) — SOUL references a dead skill and conflicting rate limits
   - [`examples/demo-agent-autonomy/`](examples/demo-agent-autonomy/) — agent auto-fixes port mismatch, escalates memory conflict
   - [`examples/demo-hill-climb/`](examples/demo-hill-climb/) — 10 accumulated patterns → 2 clusters → 2 optimization proposals
   - [`examples/demo-kb-duplication/`](examples/demo-kb-duplication/) — the same deploy instruction is copied into README/docs/wiki
4. **Run the structural validator**:
   ```bash
   python scripts/validate_context_gc.py
   ```
5. **Run the offline eval fixtures**:
   ```bash
   python scripts/run_evals.py
   ```
6. **Optional: install hooks** using [`examples/claude-settings-hooks.json`](examples/claude-settings-hooks.json). Hooks create dirty cards in `.context-gc/dirty.jsonl`, remind you to run MARK, and can block unapproved sweeps.

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

Full research notes and design rationale: [`research/context-gc-research.md`](research/context-gc-research.md).

## What it covers

- **Docs & READMEs** — stale, contradictory, or orphaned claims
- **SDD & specs** — design/spec text that diverged from code after requirement changes
- **Configs** — local↔server drift, masked configs, fork-noted divergence
- **Knowledge bases** — bloat, duplication, ever-growing append-only decay
- **Agent context** — SOUL/CLAUDE.md/skills/memory context rot (stale instructions, semantic conflicts, dead references, memory leak, skill bloat, tone drift)
- **Agent memory layers** — long-term, mid-term, and profile memory that conflict or drift; `memory-condense` writes one current memory and keeps originals as evidence
- **A single session** — transcript/session rot: superseded plans, orphaned TODOs, repeated decisions, and tool-output bloat
- **Preventive Minor GC** — automated agents can periodically check dirty context and apply only pre-authorized safe fixes before drift spreads
- **Layer 4 Hill Climbing** — accumulated patterns from successful resolutions feed back to improve drift detection automatically

## Loop Engineering

context-gc maps to the four-layer Loop Engineering architecture defined by LangChain (2026.06):

| Layer | context-gc | Status |
|---|---|---|
| L1 Agent Loop | Sidecar — doesn't participate in agent orchestration | — |
| L2 Verification | `gc_tick --gate` — deterministic checks + LLM review after every task | ✅ |
| L3 Event-driven | hooks dirty-card → auto-MARK → gc_tick on interval | ✅ |
| L4 Hill Climbing | `analyze_patterns.py` — clusters patterns, auto-suggests optimizations | ✅ |

Full design: [`references/loop-engineering.md`](references/loop-engineering.md) · Architecture: [`references/architecture.md`](references/architecture.md)

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
files, `Stop` reminds you to run MARK before entropy accumulates, and optional `PreToolUse`
guards block unapproved bulk sweeps. See
[`references/hooks.md`](references/hooks.md) and
[`examples/claude-settings-hooks.json`](examples/claude-settings-hooks.json).

## Why not just use docs linters?

Use them. `context-gc` is not a replacement for Vale, markdownlint, lychee, or project-specific
checks. Those tools are scanners: they produce evidence during MARK. `context-gc` is the collector
protocol around them: find roots, trace claims, confirm SWEEP, then record the root→copy map in
`SOURCES.md` so the same drift is cheaper to catch next time.

Read the full skill: [`SKILL.md`](SKILL.md)

## Files

```
context-gc/
├── .editorconfig                    # Cross-platform text encoding and LF endings
├── .github/workflows/validate.yml   # GitHub Actions validation
├── .claude/
│   ├── settings.json                # PostToolUse ruff check hook (dev)
│   └── skills/verify-gc/SKILL.md    # /verify-gc skill for contributors
├── CLAUDE.md                        # Project instructions for Claude Code
├── SKILL.md                         # Full skill — GC cycle, safety rules, output formats
├── SOURCES.md                       # Dogfooded authority map for this repo
├── README.md                        # This file (English)
├── README.zh-CN.md                  # Chinese README
├── INSTALL.md                       # Install guide — one-command, hooks, CI, any agent platform
├── INSTALL_AGENT.md                 # Tell your agent to install — one paste
├── CONTRIBUTING.md                  # Contributor workflow and validation commands
├── install.py                       # One-command installer (curl ... | python3)
├── pyproject.toml                   # ruff formatter/linter config
├── evals/
│   └── evals.json                   # 29 machine-readable eval scenarios
├── research/
│   ├── context-gc-research.md       # GC metaphor sources and design rationale
│   └── loop-integration-plan.md     # Loop engine integration development plan
├── references/
│   ├── gc-model.md                  # GC ↔ entropy mental model
│   ├── entropy-checklist.md         # Garbage taxonomy + detection methods
│   ├── treatment-playbook.md        # Per-type sweep actions
│   ├── hooks.md                     # Optional Claude Code hook recipes
│   ├── mcp-surface.md               # MCP tool surface design (deferred server)
│   ├── architecture.md              # Architecture — Blackboard + Observer + Strategy + Sidecar
│   └── loop-engineering.md          # context-gc × LangChain Loop Engineering 4 layers
├── scripts/
│   ├── _common.py                   # Shared: context detection, autonomy policy, never_auto floor
│   ├── context_gc_hook.py           # Hook helper: dirty cards, guards, reminders, auto-MARK, minor GC
│   ├── init_context_gc.py           # Bootstrap SOURCES.md + config.yml + guided setup
│   ├── mark.py                      # Mechanical MARK: docs/config/agent/memory drift candidates
│   ├── minor_gc.py                  # Preventive Minor GC with pre-authorized safe fixers
│   ├── review_queue.py              # Aggregate open decisions → review-queue.json
│   ├── resolve.py                   # Agent self-resolve within autonomy policy + audit log
│   ├── gc_tick.py                   # One governance tick — any loop/agent entry point
│   ├── analyze_patterns.py          # Layer 4 hill climbing — cluster patterns, suggest optimizations
│   ├── session_mark.py              # MARK exported transcripts for session context rot
│   ├── run_evals.py                 # Offline eval fixture checker
│   ├── validate_context_gc.py       # Structural validator + dogfood self-check
│   ├── install.sh                   # One-command installer (Linux/macOS)
│   ├── install.ps1                  # One-command installer (Windows PowerShell)
│   └── adapters/
│       └── hermes_adapter.py        # Hermes/Ralph loop integration (gate, emit-tasks, compact)
├── examples/
│   ├── claude-settings-hooks.json   # Example .claude/settings.json hook config
│   ├── demo-doc-vs-config/         # Stale README vs live docker-compose port
│   ├── demo-sdd-drift/             # SDD diverged from implementation after requirements changed
│   ├── demo-agent-context-rot/     # Dead skill + conflicting agent instructions
│   ├── demo-agent-drift-advanced/  # Semantic conflicts, memory leak, skill bloat, session rot
│   ├── demo-minor-gc/              # Pre-authorized scalar-sync safe auto-fix
│   ├── demo-memory-drift/          # memory-condense long/mid-term memory + profile drift
│   ├── demo-review-queue/          # Pre-seeded review-queue fixture
│   ├── demo-agent-autonomy/        # Agent self-resolve port mismatch, escalate memory conflict
│   ├── demo-hill-climb/            # 10 patterns → 2 clusters → 2 optimization proposals
│   └── demo-kb-duplication/        # Same fact copied across README/docs/wiki
└── templates/
    └── SOURCES.md.template          # Authority map template (the write barrier)
```

## Development

```bash
python scripts/validate_context_gc.py
python scripts/run_evals.py
```

This repo dogfoods its own write barrier in [`SOURCES.md`](SOURCES.md). When changing the skill,
hooks, demos, or GitHub metadata, update the matching authority-map entry if the root→copy
relationship changes.

## License

MIT — fork, remix, dogfood, contribute.

## See also

- [LogRocket: Context rot is slowing down your AI agent](https://blog.logrocket.com/context-rot-slowing-down-your-ai-agent-how-fix/)
- [MindStudio: What is context rot and how do you prevent it?](https://www.mindstudio.ai/blog/what-is-context-rot-ai-agents)
- [Josys: Configuration drift lifecycle](https://josys.com/article/understanding-the-lifecycle-of-configuration-drift-detection-remediation-and-prevention)
- [Computhink: SSoT in document governance](https://computhink.com/blog/why-a-single-source-of-truth-is-critical-for-enterprise-document-governance/)
