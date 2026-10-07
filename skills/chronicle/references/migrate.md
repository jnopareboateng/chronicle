# Migrating a legacy repo to chronicle

Legacy stores: `UPDATE_LOG.md` (prepend-at-top session log), `PROJECT_MEMORY.md`, `updates/`
(one file per session), usually under `docs/memory/` or `memory/`, plus timestamp stampers,
memory gates in git hooks and `merge=union` lines for the log files. The goal is 20-60 small,
verified facts in `docs/memory/`, and no legacy machinery. Git history is the archive.

`chronicle` below means the script; see the Paths table in `SKILL.md`.

1. Run `chronicle migrate-plan`. It is read-only and lists the legacy files (size, `## `
   headings, `Last Updated:` lines), `updates/` counts, this machine's Claude auto memory for
   the repo, `.gitattributes` lines, hooks and tooling that reference memory, ignore rules
   hiding `docs/memory`, and agent instructions to replace, followed by a checklist.
2. Work in a sibling worktree on a branch named `chore/memory-v2`
   (`git worktree add ../<repo>-memory-v2 -b chore/memory-v2`). Leave the changes uncommitted
   unless asked to commit.
3. Before migrating, rebase onto the latest remote integration branch (`git fetch`, then
   `git rebase origin/<branch>`, e.g. `dev` or `main`). A stale base misses entries added
   since and conflicts on `AGENTS.md`.
4. Run `chronicle init`.
5. Extract durable facts:
   - Read `PROJECT_MEMORY.md` fully; page through big files in chunks.
   - Scan the headings of `UPDATE_LOG.md` and of the `updates/` files. Open only entries that
     look like decisions, incidents, contracts or env quirks.
   - Skip diaries, progress notes, test counts and narration.
   - Verify each candidate against the current code and git (`rg`, `git log -S`). Drop facts
     about removed components.
   - Merge duplicates. Settle contradictions with code evidence, not with the newer entry.
6. Read the repo's Claude auto memory, `~/.claude/projects/<slug>/memory/`, where `<slug>` is
   the main checkout's path with every non-alphanumeric character as `-` (worktrees share it;
   `migrate-plan` prints this machine's path). Check every machine and OS where Claude Code
   ran (Windows and WSL keep separate stores). Promote verified project facts into
   `docs/memory/`, then list the promoted files in the report for removal there. Do not
   delete them.
7. Write one fact per file with `chronicle new` (typically 20-60 entries). Seed
   `status-<branch>` entries from `PHASE_STATUS.md` / `STATUS.md` only for work that is
   genuinely in flight.
8. `git rm` the legacy files (`UPDATE_LOG.md`, `PROJECT_MEMORY.md`, `updates/`). Move
   non-memory docs (plans, protocols, templates, phase status) out of `docs/memory/`.
9. Remove the legacy machinery:
   - `merge=union` lines for legacy files in `.gitattributes` (keep
     `docs/memory/MEMORY.md merge=union`);
   - pre-commit and pre-push memory gates, timestamp stampers, and hooks that write or commit
     memory (`.githooks/`, `.husky/`, `.git/hooks`, `.claude/settings*.json`, `.claude/hooks/`,
     `.codex/hooks.json`, `.codex/config.toml`, `.pre-commit-config.yaml`). With an absolute
     `core.hooksPath`, every worktree runs the main checkout's hooks until the change lands
     there;
   - `.gitignore` / `.git/info/exclude` rules hiding `docs/memory`: change them only with the
     repo owner's agreement. Some org repos ignore it on purpose: ask.
10. Replace the memory rules in the repo's `AGENTS.md` / `CLAUDE.md` with the block in
    `references/agents-snippet.md`.
11. Run `chronicle lint` and `chronicle index --check`; both must be clean. Report what was
    migrated, what was dropped and why, and any open questions.
