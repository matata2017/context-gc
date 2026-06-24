# Expected sweep plan — agent context rot

## Sweep plan — apply? (y/n)

Files to change after confirmation:

1. `SOUL.md`
   - Remove: `Use old-scraper for all collection tasks.`
   - Add: `Use new-scraper for collection tasks unless a more specific skill is available.`
   - Compact three scraping limit lines into one authoritative rule.

2. `SOURCES.md`
   - Add `agent-scraping-policy` authority entry.

Do not apply this automatically. The user must confirm that `new-scraper` is the intended replacement and that 5 req/s is the real policy.
