---
name: chronicle-write
description: Guided ritual for writing to project memory files. Use before any write to PROJECT_MEMORY.md, UPDATE_LOG.md, or PHASE_STATUS.md to ensure correct timestamp, format, and entry ordering.
---

# chronicle:write — Memory Write Ritual

## Step 1 — Get a fresh timestamp

**Never hand-type. Never reuse the session-start timestamp.**

```bash
# Any project (chronicle portable):
python3 ~/.claude/plugins/chronicle/scripts/timestamp.py

# DocinaBox (project-local, preferred when present):
python3 scripts/agent_harness/current_timestamp.py
```

Copy the output verbatim. Example output: `Tuesday, 24-06-2026, 3:15 pm`

## Step 2 — Update the file header

Replace the `Last Updated:` line at the very top of the target file:

```
Last Updated: Tuesday, 24-06-2026, 3:15 pm
```

## Step 3 — Build your entry

Two layers, no subheading between them:

```markdown
## Tuesday, 24-06-2026, 3:15 pm, [branch-name] Short title

- Plain-language bullet (outcome, decision, or risk — readable by a stakeholder)
- Plain-language bullet 2 (if needed, max 4 total)

- Technical detail: file:line, migration name, API contract, failure mode
- Technical detail 2 (if needed, max 4 total)
```

**Format rules:**
- Day is spelled out: `Tuesday` not `Tue`
- Date is DD-MM-YYYY: `24-06-2026`
- Time has no leading zero, lowercase am/pm: `3:15 pm` not `03:15 PM`
- Branch name in square brackets: `[dev]` not `<dev>`
- Title describes WHAT and WHY, not the process ("Added X to fix Y" not "Updated file")
- No process narration: no "spawned agents", "wave 3", model choices, tool counts

## Step 4 — Prepend the entry

Insert your new `## ` entry **immediately after** the `Last Updated:` line (and any `---` separator). Newest entries are always at the **top** of the file.

## Step 5 — Sync (recommended)

After writing, propagate to both native stores so the other agent sees it next session:

```bash
python3 ~/.claude/plugins/chronicle/scripts/sync.py
```

Or invoke `chronicle:sync` if available.
