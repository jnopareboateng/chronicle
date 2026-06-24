# chronicle — Memory Write Protocol

All agents writing to project memory files MUST follow this protocol.
Violations break the harness validation gate and cause commit failures.

## Canonical memory files

```
docs/memory/PROJECT_MEMORY.md   ← durable facts, decisions, rationale
docs/memory/UPDATE_LOG.md       ← chronological session log
docs/PHASE_STATUS.md            ← current phase and blockers
```

These are git-tracked and shared between Claude and Codex. They are the source of truth.

## Before every memory write

1. **Get a fresh timestamp** — never hand-type or reuse the session-start timestamp:

   ```bash
   python3 ~/.claude/plugins/chronicle/scripts/timestamp.py
   # or project-local (DocinaBox): python3 scripts/agent_harness/current_timestamp.py
   ```

2. **Update `Last Updated:`** at the top of the file with that exact value.

3. **Prepend your entry** — newest entries go at the TOP, below the header.

4. **Two-layer format** (no subheading between layers):

   ```
   ## Day, DD-MM-YYYY, H:MM am/pm, [branch] Short title

   - Plain-language summary (outcome/decision/risk — readable by a stakeholder)

   - Technical detail (file:line, migration, API contract, failure mode)
   ```

5. **Timestamp format** (must match `^[A-Za-z]+, \d{2}-\d{2}-\d{4}, \d{1,2}:\d{2} (?:am|pm)`):
   - Day spelled out: `Tuesday`
   - Date: `24-06-2026` (DD-MM-YYYY)
   - Time: `3:15 pm` (no leading zero, lowercase am/pm)
   - Branch in square brackets: `[dev]`

## After writing

Run sync to propagate to both native stores:

```bash
python3 ~/.claude/plugins/chronicle/scripts/sync.py
```

This ensures the other agent sees the new entries in their next session.

## Cross-agent visibility

- `chronicle:write` skill — guided write ritual (Claude Code + Codex)
- `chronicle:sync` skill — bidirectional sync management
- The PreToolUse hook **blocks** writes with malformed timestamps automatically (Claude Code only; Codex relies on this protocol)
