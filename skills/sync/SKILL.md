---
name: chronicle-sync
description: Synchronize canonical project memory to both Claude and Codex native stores, and surface what native stores have that canonical doesn't yet. Run after any memory write or at the start of a cross-agent session.
---

# chronicle:sync — Memory Synchronization

## What this does

```
canonical docs/memory/*.md
       │
       ▼  (automatic)
Claude ~/.claude/projects/<slug>/memory/chronicle_sync.md
Codex  ~/.codex/memories/chronicle_sync.md
       │
       ▼  (supervised — you review before writing)
canonical docs/memory/*.md  ← new entries from native stores
```

## Forward sync: canonical → native (automatic)

Propagates the most recent entries from canonical files to both native stores.
Both agents will see the new content in their next session.

```bash
python3 ~/.claude/plugins/chronicle/scripts/sync.py
```

## Reverse diff: native → canonical (supervised)

Shows what Codex and Claude native stores contain that canonical doesn't yet have.
**Nothing is written automatically** — you review and confirm each entry.

```bash
python3 ~/.claude/plugins/chronicle/scripts/sync.py --reverse
```

For each entry worth preserving: invoke `chronicle:write` and write it to the
appropriate canonical file. Canonical is git-tracked — every write is recoverable.

## Full sync (forward + reverse diff)

```bash
python3 ~/.claude/plugins/chronicle/scripts/sync.py --full
```

## When to run

- After any write to canonical memory
- At the start of a session that follows a Codex review run
- When starting collaborative work across agents to ensure both are current
