---
name: chronicle
description: Shared project memory kept in the repo (docs/memory/MEMORY.md index, one fact per file, synced by git). Use when starting work in a repo (recall relevant entries), after meaningful work (write decisions, gotchas, contracts, env quirks, status), when memory looks stale, wrong or duplicated (curate), or when a repo still has legacy UPDATE_LOG.md, PROJECT_MEMORY.md or updates/ files (migrate). Not for personal preferences or machine-only quirks.
---

# chronicle: shared project memory

Project memory lives in the repo at `docs/memory/`, so git carries it to every person, agent,
machine and worktree. `MEMORY.md` is a generated index; each `<slug>.md` holds one fact.
Full format and examples: `references/format.md`.

## Memory layers

| Layer | Where | Holds |
|---|---|---|
| Shared project memory | `<repo>/docs/memory/` | The ONLY home for project facts: decisions, contracts, gotchas, env quirks, references, in-flight status. |
| Personal memory | Claude auto memory, Codex memory summary | Machine-level or personal quirks only. Never project facts: they would not reach teammates or other agents. |
| Global rules | the user's global `AGENTS.md` | Cross-project preferences. A preference the user states twice graduates here. |

## Recall (start of work)

1. A SessionStart hook injects the index (`chronicle context`). Without the hook, read
   `docs/memory/MEMORY.md` yourself.
2. Open only the entries relevant to the task. Never read the whole store.
3. Never bulk-read legacy `UPDATE_LOG.md` or `updates/`. For a legacy `PROJECT_MEMORY.md`, read
   its section headings, then only the matching sections.
4. Code wins over memory. When an entry contradicts the code, fix or delete the entry now.

## Write (after meaningful work)

Write when the work produced a durable fact:
- a decision and its rationale
- a failure mode: symptom -> cause -> guard
- an API, schema or integration contract
- an environment or tooling quirk
- a pointer to an external resource (dashboard, doc, runbook)
- status of multi-session work (`status-<branch>`; delete it when the work merges)

Never write: session narration, which agent/model/effort did the work, test counts, anything
derivable from the code or `git log`, secrets, personal data, transcripts.

How:
1. Check the index for an entry that already covers the fact. If one does, update it and bump
   `updated:`. Otherwise run `chronicle new <type> <slug> --description "..."`.
2. Fill the body: the fact first (1-6 lines), then `**Why:**` and `**How to apply:**`.
   The description is one specific line of at most 100 chars; it decides whether the entry
   gets recalled.
3. One fact per file. Optional last line: `Related: [[other-slug]]`.
4. Run `chronicle index`, then `chronicle lint`.
5. Commit memory together with the related code change, following the repo's conventions.
   No memory-only auto-commits. No hook ever writes memory.

## Curate (stale, wrong or duplicated memory)

- Superseded decision: rewrite the entry to the current decision and add a
  `Supersedes: <old decision, date>` line. Never keep two contradicting entries.
- Delete `status-*` entries once their work has merged.
- Delete entries that restate the code. Merge duplicates into one entry.
- Act on `chronicle lint` budget warnings: split or tighten big entries; past 80 entries or a
  9000-byte `MEMORY.md`, prune before adding (beyond that, session start lists the tail by
  name only).
- After a merge or rebase that touched `docs/memory/`: `chronicle index`, then `chronicle lint`.

## Migrate (legacy UPDATE_LOG.md / PROJECT_MEMORY.md / updates/)

Run `chronicle migrate-plan` (read-only) and follow `references/migrate.md`. A migration is a
deliberate task: propose it when you meet a legacy store, run it when asked.

## Commands

| Command | Does |
|---|---|
| `context [--max-bytes N]` | Print the index for session-start injection (past the cap, remaining entries by name); never fails |
| `index [--check]` | Regenerate `MEMORY.md`; `--check` writes nothing, exits 1 if stale |
| `lint [--strict]` | Validate format, budgets, secrets, index drift; `--strict` fails on warnings |
| `new <type> <slug> --description TEXT` | Scaffold an entry (refuses to overwrite) and reindex |
| `init` | Create `docs/memory/`, `MEMORY.md` and the `.gitattributes` union line |
| `migrate-plan` | Read-only inventory and checklist for a legacy repo |
| `install [--claude] [--codex] [--hooks]` | Copy this skill to `~/.claude` / `~/.codex`; optional SessionStart hook |

Every command takes `--cwd DIR` (any directory inside the repo). Types: `status`, `decision`,
`contract`, `gotcha`, `env`, `reference`. Without the script, edit the files by hand: the
format is repeated in the `MEMORY.md` header.

## Paths

| Platform | Command |
|---|---|
| WSL / Linux, Claude Code | `python3 ~/.claude/skills/chronicle/scripts/chronicle.py <command>` |
| WSL / Linux, Codex | `python3 ~/.codex/skills/chronicle/scripts/chronicle.py <command>` |
| Windows (cmd), Claude Code | `py -3 "%USERPROFILE%\.claude\skills\chronicle\scripts\chronicle.py" <command>` |
| Windows (cmd), Codex | `py -3 "%USERPROFILE%\.codex\skills\chronicle\scripts\chronicle.py" <command>` |
| Windows (PowerShell), Claude Code | `py -3 "$env:USERPROFILE\.claude\skills\chronicle\scripts\chronicle.py" <command>` |
| Windows (PowerShell), Codex | `py -3 "$env:USERPROFILE\.codex\skills\chronicle\scripts\chronicle.py" <command>` |
| Windows (Git Bash), Claude Code | `py -3 ~/.claude/skills/chronicle/scripts/chronicle.py <command>` |
| Windows (Git Bash), Codex | `py -3 ~/.codex/skills/chronicle/scripts/chronicle.py <command>` |

WSL and Windows have separate homes: run `install` on each OS with that OS's Python. From WSL,
`install --hooks --home /mnt/c/Users/<you>` writes a Linux hook command that Windows agents
cannot run (install warns); run the Windows `py -3 ... install --hooks` instead.
