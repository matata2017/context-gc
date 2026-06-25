# Demo: advanced agent drift

This fixture shows deeper agent-context entropy:

- semantic policy conflict across `CLAUDE.md`, `SOUL.md`, and memory;
- append-only memory variants;
- overlapping skills;
- tone/behavior drift;
- session transcript rot.

Run:

```bash
python scripts/mark.py --target examples/demo-agent-drift-advanced
python scripts/session_mark.py --target examples/demo-agent-drift-advanced --transcript examples/demo-agent-drift-advanced/transcript.md
```
