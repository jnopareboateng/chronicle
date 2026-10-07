# AGENTS.md: developing chronicle

chronicle is one installable skill folder plus its tests.

| Path | What |
|---|---|
| `skills/chronicle/SKILL.md` | The skill both Claude Code and Codex load (router style, at most 130 lines) |
| `skills/chronicle/references/` | `format.md` (the contract), `migrate.md`, `agents-snippet.md` |
| `skills/chronicle/scripts/chronicle.py` | The CLI: context, index, lint, new, init, migrate-plan, install |
| `tests/test_chronicle.py` | unittest suite (temp dirs, no network) |

## Test

```bash
python3 -m unittest discover -s tests -v        # Linux / WSL
py -3 -m unittest discover -s tests -v          # Windows
```

## Rules

- Stdlib only, Python 3.8+: no third-party packages, no YAML library.
- `references/format.md` is the contract. Change the spec, the script and the tests together.
- `context` runs in SessionStart hooks: it must never raise, never exit non-zero, and stay fast
  (under 200 ms on a 100-file store on Linux/WSL; Windows interpreter startup alone is
  150-300 ms). Import heavy modules (argparse, json, shutil, subprocess) only where used.
- `migrate-plan` is read-only. `install` preserves every existing setting and hook, backs files
  up before changing them, and is idempotent.
- Paths must work for git worktrees (`.git` file), Windows and UNC paths.
- Keep `SKILL.md` within 130 lines and its description within 600 characters.
