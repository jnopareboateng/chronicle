# chronicle

Memory write enforcement and cross-agent sync for Claude Code + Codex.

Solves two problems that compound over time in multi-agent engineering workflows:
1. Agents hand-type or reuse stale timestamps → harness validation failures and blocked commits.
2. Claude and Codex work from separate memory silos → findings from one agent never reach the other.

## What it does

| Component | What |
|---|---|
| `PreToolUse` hook | Blocks any `Write`/`Edit` to a memory file where `Last Updated:` fails the canonical timestamp format |
| `chronicle:write` skill | Step-by-step guided ritual: fetch timestamp → format two-layer entry → prepend |
| `chronicle:sync` script + skill | Canonical `docs/memory/` → Claude + Codex native stores (forward); native stores → canonical diff (supervised reverse) |
| `AGENTS.md` | Global injection — both Claude and Codex see the write protocol at session start |

## Install

```bash
# Claude Code
claude plugin install github:jnopareboateng/chronicle

# Wire up Codex (run once after the above)
python3 ~/.claude/plugins/chronicle/scripts/install-codex.py
```

## Usage

### Writing to memory

Invoke the skill before any memory file write:

```
chronicle:write    (Claude Code)
chronicle-write    (Codex skill)
```

Or just follow the protocol in AGENTS.md. The hook will block you if the timestamp is wrong.

### Syncing across agents

```bash
# Forward: canonical → both native stores
python3 ~/.claude/plugins/chronicle/scripts/sync.py

# Reverse diff: show what native stores have that canonical doesn't
python3 ~/.claude/plugins/chronicle/scripts/sync.py --reverse

# Both
python3 ~/.claude/plugins/chronicle/scripts/sync.py --full
```

### Getting a fresh timestamp

```bash
python3 ~/.claude/plugins/chronicle/scripts/timestamp.py
```

## Canonical memory file locations

The sync script looks for these files relative to the current working directory:

```
docs/memory/PROJECT_MEMORY.md
docs/memory/UPDATE_LOG.md
```

And validates writes to any file named `PROJECT_MEMORY.md`, `UPDATE_LOG.md`,
`PHASE_STATUS.md`, or any `*.md` under `docs/memory/`.

## Timestamp format

```
Last Updated: Tuesday, 24-06-2026, 3:15 pm
```

Regex: `^[A-Za-z]+, \d{2}-\d{2}-\d{4}, \d{1,2}:\d{2} (?:am|pm)`

## Two-layer entry format

```markdown
## Tuesday, 24-06-2026, 3:15 pm, [branch-name] Short title

- Plain-language summary (readable by a non-technical stakeholder)
- Outcome, decision, or risk

- Technical detail: file:line, migration, API contract, failure mode
- What a future engineer needs to know
```

Newest entries go at the **top**, below the `Last Updated:` header.

## Sync design

```
canonical docs/memory/*.md  (git-tracked, source of truth)
       │
       ▼  automatic
  ┌────┴────┐
Claude    Codex
native    native
  └────┬────┘
       │
       ▼  supervised (you review + confirm)
canonical docs/memory/*.md
```

Forward sync is automatic and safe (overwrites the `chronicle_sync.md` mirror file in each native store).
Reverse sync is supervised — the script shows a diff and the agent writes to canonical using `chronicle:write`, one entry at a time.

## Codex enforcement note

The `PreToolUse` hook runs in Claude Code only. Codex gets behavioral enforcement
via `AGENTS.md` + the `chronicle-write` skill. Hard block enforcement for Codex
is deferred until Codex exposes a documented hook surface.

## License

MIT
