#!/usr/bin/env python3
"""chronicle: post-install script for Codex-side wiring.

Run once after `claude plugin install github:jnopareboateng/chronicle`:

    python3 ~/.claude/plugins/chronicle/scripts/install-codex.py

What it does:
  1. Copies chronicle skill files to ~/.codex/skills/
  2. Adds an @-reference to AGENTS.md in ~/.codex/AGENTS.md
"""
import shutil
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CODEX_HOME = Path.home() / ".codex"
CODEX_SKILLS = CODEX_HOME / "skills"
CODEX_AGENTS = CODEX_HOME / "AGENTS.md"


def install_skills() -> None:
    CODEX_SKILLS.mkdir(parents=True, exist_ok=True)
    for src_dir in (PLUGIN_ROOT / "codex-skills").iterdir():
        if not src_dir.is_dir():
            continue
        dst = CODEX_SKILLS / src_dir.name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_dir, dst)
        print(f"[chronicle] ✓ installed Codex skill: {dst.name}")


def wire_agents_md() -> None:
    ref = f"@{PLUGIN_ROOT}/AGENTS.md"
    if CODEX_AGENTS.exists():
        existing = CODEX_AGENTS.read_text(encoding="utf-8")
        if ref in existing:
            print(f"[chronicle] ✓ AGENTS.md already references chronicle")
            return
        updated = f"{ref}\n\n{existing}"
    else:
        updated = f"{ref}\n"
    CODEX_AGENTS.write_text(updated, encoding="utf-8")
    print(f"[chronicle] ✓ added chronicle reference to {CODEX_AGENTS}")


def main() -> None:
    if not CODEX_HOME.exists():
        print(f"[chronicle] ~/.codex not found — is Codex installed?")
        sys.exit(1)

    install_skills()
    wire_agents_md()
    print("\n[chronicle] Codex wiring complete.")
    print("  Skills installed:  chronicle-write, chronicle-sync")
    print(f"  AGENTS.md updated: {CODEX_AGENTS}")


if __name__ == "__main__":
    main()
