# Expected entropy report — agent context rot

## Entropy report — examples/demo-agent-context-rot

Status legend: SYNCED | DRIFTED | NOT_CHECKED | FORK | UNKNOWN_ROOT

🟠 ORPHAN      DRIFTED  SOUL.md:3  refers to `old-scraper`, but no `skills/old-scraper/SKILL.md` exists  → repoint/delete

🔴 CONTRADICTION  DRIFTED  SOUL.md:6-7  "Limit scraping to 10 req/s" ↔ "Never exceed 5 req/s"  → compact to one authoritative policy

🟡 DUPLICATE / CONFUSION  UNKNOWN_ROOT  SOUL.md:6-8 has three overlapping scraping policy statements  → compact

## Why

This is agent context rot:

- **Orphan:** the agent is instructed to use a deleted skill.
- **Clash:** two numeric limits cannot both be the primary rule unless one is explicitly a maximum and the other a fallback.
- **Confusion:** overlapping instructions make future tool choice and rate limits unpredictable.

## Sweep plan — apply? (y/n)

- `SOUL.md`: replace `old-scraper` with `new-scraper` if user confirms it is the replacement root.
- `SOUL.md`: compact scraping policy to one rule, for example: "Use official APIs first; if scraping is required, cap at 5 req/s or lower."
- `SOURCES.md`: add an `agent-scraping-policy` entry with `skills/new-scraper/SKILL.md` or `SOUL.md` as the confirmed root.
