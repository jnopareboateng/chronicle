# chronicle

Shared project memory for people and coding agents (Claude Code, Codex), stored in the repo.
Git syncs it to every person, agent, machine and worktree.

## Problem

Agent memory written as one timestamped log per repo (`UPDATE_LOG.md` prepended at the top,
`PROJECT_MEMORY.md`) grows to hundreds of KB, drifts into many timestamp formats, conflicts on
every parallel branch, and buries the few durable facts under session diaries. Mirroring it
into a tool's global memory store leaks one project's facts into others.

chronicle v2 keeps memory the way Claude Code's auto memory does (an index plus one fact per
file) but inside the repo, where review, history and merges already work.

## Format

```
docs/memory/
  MEMORY.md                  generated index, injected at session start
  auth-session-cookies.md    one fact per file
  status-feat-billing.md
```

```markdown
---
name: auth-session-cookies
description: Browser auth uses HttpOnly session cookies backed by the sessions table, not JWTs
type: decision
updated: 2026-09-14
---
Browser clients authenticate with an opaque session id in an HttpOnly cookie.

**Why:** Role changes must revoke access immediately; JWT expiry windows could not.
**How to apply:** New browser endpoints read `request.session`; never issue JWTs to browsers.
```

Types: `status`, `decision`, `contract`, `gotcha`, `env`, `reference`. `MEMORY.md` lists
entries by section, sorted by name, and is union-merged by git (`.gitattributes`), so parallel
branches do not conflict. Descriptions stay within 100 chars, so about 60 entries fit the
9000-byte session-start budget in full; past it, the remaining entries are listed by name.
Full spec, budgets and examples:
[`skills/chronicle/references/format.md`](skills/chronicle/references/format.md).

Nobody needs the tool to read or write memory: it is plain Markdown, and the format is
repeated in the `MEMORY.md` header.

## Install (teammates)

The skill is one folder: `skills/chronicle/`. The installer copies it into `~/.claude/skills/`
and/or `~/.codex/skills/` (whichever exist) and, with `--hooks`, adds a SessionStart hook that
prints the repo's memory index into every new, resumed, cleared or compacted session (and, in
Claude Code, forked session).

```bash
git clone https://github.com/jnopareboateng/chronicle
python3 chronicle/skills/chronicle/scripts/chronicle.py install --hooks       # Linux, WSL, macOS
py -3 chronicle\skills\chronicle\scripts\chronicle.py install --hooks         # Windows
```

- `--claude` / `--codex` pick targets; `--home DIR` and `--python CMD` override defaults.
- Existing settings and hooks are preserved, in place and in order; a reinstall updates the
  chronicle hook's command where it is and keeps a customized `timeout` or
  `additionalContextLimit`. Before the first change, `settings.json` / `hooks.json` are
  copied to `*.bak-chronicle`; later runs keep that original. Symlinked files are written
  through. The skill folder is replaced only once the new copy is in place; a failed copy
  leaves the previous installation as it was. Rerunning is safe.
- Install natively on each OS: WSL and Windows have separate homes. From WSL,
  `--home /mnt/c/Users/<you> --hooks` would write a Linux hook command that Windows cannot run
  (install warns); run the Windows command above instead.
- Codex runs a new or changed hook only after you trust it: open Codex and run `/hooks`.
- Codex documents `~/.agents/skills/` as the user skill folder; Codex 0.159 still loads
  `~/.codex/skills/`, which is where `install` puts the skill.

Then, in each repo: `chronicle init` (creates `docs/memory/` and the `.gitattributes` line) and
paste [`references/agents-snippet.md`](skills/chronicle/references/agents-snippet.md) into the
repo's `AGENTS.md`.

### Upgrading from v1

Remove v1 pieces after installing v2: `~/.claude/plugins/chronicle/`, the v1 `PreToolUse`
`validate-write.py` hook entry in `~/.claude/settings.json`, `~/.codex/skills/chronicle-write/`,
`~/.codex/skills/chronicle-sync/`, and the `chronicle_sync.md` mirrors in
`~/.codex/memories/` and `~/.claude/projects/*/memory/`. Migrate repos with `migrate-plan`.

## Commands

Run `chronicle.py <command> --cwd <dir-in-repo>` (`--cwd` defaults to `.`).

| Command | Does |
|---|---|
| `context [--max-bytes 9000]` | Print the index for SessionStart hooks (past the cap, remaining entries by name); prints nothing outside a memory repo; never fails |
| `index [--check]` | Regenerate `MEMORY.md`; `--check` exits 1 if it is stale |
| `lint [--strict]` | Format, budgets, secrets, personal data, index drift; `LEVEL path: message` per line |
| `new <type> <slug> --description TEXT` | Scaffold a memory (refuses to overwrite) and reindex |
| `init` | Create `docs/memory/`, `MEMORY.md` and `docs/memory/MEMORY.md merge=union`; idempotent |
| `migrate-plan` | Read-only inventory and checklist for repos with `UPDATE_LOG.md` / `PROJECT_MEMORY.md` |
| `install [--claude] [--codex] [--home DIR] [--hooks] [--python CMD]` | Install the skill, optionally the hook |

How agents use it (recall, write, curate, migrate): [`skills/chronicle/SKILL.md`](skills/chronicle/SKILL.md).

### Optional guards

`merge=union` keeps both sides' `MEMORY.md` lines, so a merge can leave stale or duplicate
lines behind. `chronicle lint` as a pre-commit hook and `chronicle index --check` in CI catch
that drift. chronicle installs neither; wire them into the repo's own hooks and CI if wanted.

## Development

See [`AGENTS.md`](AGENTS.md). Stdlib-only Python 3.8+; tests: `python3 -m unittest discover -s tests -v`.

## License

MIT
