#!/usr/bin/env python3
"""chronicle installer — auto-detects Claude Code and Codex, installs for all found.

Usage:
    python3 install.py              # auto-detect and install everything available
    python3 install.py --claude     # Claude Code only
    python3 install.py --codex      # Codex only
    python3 install.py --uninstall  # remove from both

Remote one-liner:
    python3 <(curl -fsSL https://raw.githubusercontent.com/jnopareboateng/chronicle/main/install.py)
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()

CLAUDE_PLUGINS = HOME / ".claude" / "plugins" / "chronicle"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"
CODEX_HOME = HOME / ".codex"
CODEX_SKILLS = CODEX_HOME / "skills"
CODEX_AGENTS = CODEX_HOME / "AGENTS.md"

PLUGIN_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"

# Files/dirs to copy into the Claude plugin install dir
PLUGIN_FILES = [
    ".claude-plugin",
    "hooks",
    "scripts",
    "skills",
    "codex-skills",
    "AGENTS.md",
]


# ── detection ──────────────────────────────────────────────────────────────────

def has_claude_code() -> bool:
    return (HOME / ".claude").exists() and shutil.which("claude") is not None


def has_codex() -> bool:
    return CODEX_HOME.exists()


# ── Claude Code install ────────────────────────────────────────────────────────

def copy_plugin_files(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for name in PLUGIN_FILES:
        s = src / name
        if not s.exists():
            continue
        d = dst / name
        if s.is_dir():
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


def resolve_plugin_root(cmd: str, install_path: Path) -> str:
    return cmd.replace(PLUGIN_ROOT_VAR, str(install_path))


def load_settings() -> dict:
    if CLAUDE_SETTINGS.exists():
        try:
            return json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_settings(data: dict) -> None:
    tmp = CLAUDE_SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CLAUDE_SETTINGS)


def hook_already_wired(existing_hooks: list, command: str) -> bool:
    for group in existing_hooks:
        for h in group.get("hooks", []):
            if h.get("command", "") == command:
                return True
    return False


def wire_hooks(install_path: Path) -> None:
    hooks_json = HERE / "hooks" / "hooks.json"
    if not hooks_json.exists():
        return

    plugin_hooks = json.loads(hooks_json.read_text(encoding="utf-8")).get("hooks", {})
    settings = load_settings()

    for event, entries in plugin_hooks.items():
        existing = settings.setdefault(event, [])
        for entry in entries:
            resolved_hooks = []
            for h in entry.get("hooks", []):
                rh = dict(h)
                if "command" in rh:
                    rh["command"] = resolve_plugin_root(rh["command"], install_path)
                resolved_hooks.append(rh)

            resolved_entry = {**entry, "hooks": resolved_hooks}
            # Check dedup by command
            cmds = [h.get("command", "") for h in resolved_hooks]
            if not any(hook_already_wired(existing, c) for c in cmds):
                existing.append(resolved_entry)

    save_settings(settings)


def unwire_hooks(install_path: Path) -> None:
    if not CLAUDE_SETTINGS.exists():
        return
    settings = load_settings()
    prefix = str(install_path)
    changed = False
    for event in list(settings.keys()):
        if not isinstance(settings[event], list):
            continue
        cleaned = []
        for group in settings[event]:
            keep_hooks = [
                h for h in group.get("hooks", [])
                if prefix not in h.get("command", "")
            ]
            if keep_hooks:
                cleaned.append({**group, "hooks": keep_hooks})
            else:
                changed = True
        settings[event] = cleaned
    if changed:
        save_settings(settings)


def install_claude() -> None:
    print("[chronicle] Installing for Claude Code...")
    copy_plugin_files(HERE, CLAUDE_PLUGINS)
    wire_hooks(CLAUDE_PLUGINS)
    print(f"  ✓ plugin files  → {CLAUDE_PLUGINS}")
    print(f"  ✓ hooks wired   → {CLAUDE_SETTINGS}")
    print(f"  ✓ AGENTS.md     → auto-loaded from plugin dir")


def uninstall_claude() -> None:
    print("[chronicle] Removing Claude Code install...")
    if CLAUDE_PLUGINS.exists():
        unwire_hooks(CLAUDE_PLUGINS)
        shutil.rmtree(CLAUDE_PLUGINS)
        print(f"  ✓ removed {CLAUDE_PLUGINS}")
        print(f"  ✓ unwired hooks from {CLAUDE_SETTINGS}")
    else:
        print(f"  ✓ not installed, nothing to remove")


# ── Codex install ──────────────────────────────────────────────────────────────

def install_codex() -> None:
    print("[chronicle] Installing for Codex...")
    CODEX_SKILLS.mkdir(parents=True, exist_ok=True)

    for src_dir in (HERE / "codex-skills").iterdir():
        if not src_dir.is_dir():
            continue
        dst = CODEX_SKILLS / src_dir.name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_dir, dst)
        print(f"  ✓ skill  → {dst.name}")

    # Wire AGENTS.md reference
    ref = f"@{HERE}/AGENTS.md"
    if CODEX_AGENTS.exists():
        existing = CODEX_AGENTS.read_text(encoding="utf-8")
        if ref not in existing:
            CODEX_AGENTS.write_text(f"{ref}\n\n{existing}", encoding="utf-8")
            print(f"  ✓ AGENTS.md → {CODEX_AGENTS}")
        else:
            print(f"  ✓ AGENTS.md already wired")
    else:
        CODEX_AGENTS.write_text(f"{ref}\n", encoding="utf-8")
        print(f"  ✓ AGENTS.md → {CODEX_AGENTS}")


def uninstall_codex() -> None:
    print("[chronicle] Removing Codex install...")
    for name in ["chronicle-write", "chronicle-sync"]:
        dst = CODEX_SKILLS / name
        if dst.exists():
            shutil.rmtree(dst)
            print(f"  ✓ removed skill {name}")

    if CODEX_AGENTS.exists():
        ref = f"@{HERE}/AGENTS.md"
        text = CODEX_AGENTS.read_text(encoding="utf-8")
        if ref in text:
            cleaned = text.replace(ref + "\n\n", "").replace(ref + "\n", "").replace(ref, "")
            CODEX_AGENTS.write_text(cleaned, encoding="utf-8")
            print(f"  ✓ removed AGENTS.md reference")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="chronicle installer")
    ap.add_argument("--claude", action="store_true", help="Claude Code only")
    ap.add_argument("--codex", action="store_true", help="Codex only")
    ap.add_argument("--uninstall", action="store_true", help="Remove chronicle")
    args = ap.parse_args()

    # Default: install for everything found
    do_claude = args.claude or (not args.codex and has_claude_code())
    do_codex = args.codex or (not args.claude and has_codex())

    if not do_claude and not do_codex:
        print("[chronicle] Neither Claude Code nor Codex found.")
        print("  Claude Code: needs ~/.claude/ + claude CLI")
        print("  Codex:       needs ~/.codex/")
        sys.exit(1)

    if args.uninstall:
        if do_claude:
            uninstall_claude()
        if do_codex:
            uninstall_codex()
        print("\n[chronicle] Uninstall complete.")
        return

    if do_claude:
        install_claude()
    if do_codex:
        install_codex()

    print("\n[chronicle] Done.")
    if do_claude:
        print("  Restart Claude Code for the hook to take effect.")
    if do_codex:
        print("  Skills available: chronicle-write, chronicle-sync")


if __name__ == "__main__":
    main()
