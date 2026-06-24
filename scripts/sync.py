#!/usr/bin/env python3
"""chronicle sync: project memory propagation between canonical and native stores.

Canonical files (git-tracked, source of truth):
  docs/memory/PROJECT_MEMORY.md
  docs/memory/UPDATE_LOG.md

Native stores (per-agent, mirrored projections):
  Claude: ~/.claude/projects/<slug>/memory/chronicle_sync.md
  Codex:  ~/.codex/memories/chronicle_sync.md

Usage:
    python3 sync.py              # canonical → native (forward sync, safe)
    python3 sync.py --reverse    # show what native stores have that canonical doesn't
    python3 sync.py --full       # forward sync, then show reverse diff
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
CODEX_MEMORIES = HOME / ".codex" / "memories"

CANONICAL_FILES = [
    "docs/memory/PROJECT_MEMORY.md",
    "docs/memory/UPDATE_LOG.md",
]

HEADING_RE = re.compile(r"^##\s+[A-Za-z]+, \d{2}-\d{2}-\d{4}")
TIMESTAMP_RE = re.compile(
    r"^Last Updated: ([A-Za-z]+, \d{2}-\d{2}-\d{4}, \d{1,2}:\d{2} (?:am|pm))"
)

SYNC_MARKER = "<!-- chronicle:sync -->"
SYNC_END = "<!-- /chronicle:sync -->"
MAX_ENTRIES_PER_FILE = 5
MAX_LINES_PER_ENTRY = 10


def cwd_to_slug(cwd: Path) -> str:
    """Convert absolute path to Claude project slug format.

    Example: /home/user/projects/foo → -home-user-projects-foo
    """
    return str(cwd).replace("/", "-")


def find_claude_project_dir(cwd: Path) -> Path | None:
    if not CLAUDE_PROJECTS.exists():
        return None
    slug = cwd_to_slug(cwd)
    candidate = CLAUDE_PROJECTS / slug
    if candidate.exists():
        return candidate
    # Scan in case of path normalization differences
    for p in CLAUDE_PROJECTS.iterdir():
        if p.is_dir() and p.name == slug:
            return p
    return None


def extract_entries(content: str) -> list[dict]:
    entries, current = [], None
    for line in content.splitlines():
        if HEADING_RE.match(line):
            if current:
                entries.append(current)
            current = {"heading": line, "body": []}
        elif current is not None:
            current["body"].append(line)
    if current:
        entries.append(current)
    return entries


def extract_last_updated(content: str) -> str | None:
    for line in content.splitlines()[:5]:
        m = TIMESTAMP_RE.match(line)
        if m:
            return m.group(1)
    return None


def build_sync_section(canonical: dict[str, str], synced_at: str) -> str:
    parts = [
        SYNC_MARKER,
        f"# Chronicle Sync — {synced_at}",
        "",
        "> Mirrored from canonical project memory. Do not edit this section manually.",
        "> Run `python3 ~/.claude/plugins/chronicle/scripts/sync.py` to refresh.",
        "",
    ]
    for filename, content in canonical.items():
        last_updated = extract_last_updated(content) or "unknown"
        parts += [f"## Source: {filename}", f"_Last updated: {last_updated}_", ""]
        for entry in extract_entries(content)[:MAX_ENTRIES_PER_FILE]:
            parts.append(entry["heading"])
            parts.extend(entry["body"][:MAX_LINES_PER_ENTRY])
            parts.append("")
    parts.append(SYNC_END)
    return "\n".join(parts)


def write_with_lock(path: Path, content: str) -> None:
    """Atomic write using a temp file + rename."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def forward_sync(canonical: dict[str, str], synced_at: str) -> None:
    """canonical → both native stores."""
    section = build_sync_section(canonical, synced_at)

    # Claude
    cwd = Path.cwd()
    claude_dir = find_claude_project_dir(cwd)
    if claude_dir:
        mem_dir = claude_dir / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        target = mem_dir / "chronicle_sync.md"
        write_with_lock(target, section)
        print(f"[chronicle] ✓ Claude  → {target}")
    else:
        print(f"[chronicle] ⚠ Claude project dir not found for {cwd} — skipping")

    # Codex
    if CODEX_MEMORIES.exists():
        target = CODEX_MEMORIES / "chronicle_sync.md"
        write_with_lock(target, section)
        print(f"[chronicle] ✓ Codex   → {target}")
    else:
        print(f"[chronicle] ⚠ Codex memories dir not found ({CODEX_MEMORIES}) — skipping")


def reverse_diff(canonical: dict[str, str]) -> None:
    """Show what native stores have that canonical doesn't (supervised review)."""
    canonical_headings: set[str] = set()
    for content in canonical.values():
        for e in extract_entries(content):
            canonical_headings.add(e["heading"])

    print("\n[chronicle] Reverse diff — entries in native stores not in canonical:\n")
    found_any = False

    # Codex MEMORY.md
    codex_mem = CODEX_MEMORIES / "MEMORY.md"
    if codex_mem.exists():
        new_entries = [
            e["heading"]
            for e in extract_entries(codex_mem.read_text(encoding="utf-8"))
            if e["heading"] not in canonical_headings
        ]
        if new_entries:
            found_any = True
            print("Codex MEMORY.md:")
            for h in new_entries:
                print(f"  {h}")

    # Claude memory files
    cwd = Path.cwd()
    claude_dir = find_claude_project_dir(cwd)
    if claude_dir:
        mem_dir = claude_dir / "memory"
        if mem_dir.exists():
            for mem_file in sorted(mem_dir.glob("*.md")):
                if mem_file.name == "chronicle_sync.md":
                    continue
                try:
                    text = mem_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                new_entries = [
                    e["heading"]
                    for e in extract_entries(text)
                    if e["heading"] not in canonical_headings
                ]
                if new_entries:
                    found_any = True
                    print(f"\nClaude memory/{mem_file.name}:")
                    for h in new_entries:
                        print(f"  {h}")

    if not found_any:
        print("  Nothing new — native stores are in sync with canonical.")

    print(
        "\n[chronicle] To write any of these to canonical, use the chronicle:write skill.\n"
        "  Canonical is git-tracked — the agent confirms each entry before it lands."
    )


def main():
    ap = argparse.ArgumentParser(description="chronicle: sync project memory")
    ap.add_argument("--reverse", action="store_true", help="Show native-only entries")
    ap.add_argument("--full", action="store_true", help="Forward sync + reverse diff")
    args = ap.parse_args()

    repo_root = Path.cwd()
    canonical: dict[str, str] = {}
    for rel in CANONICAL_FILES:
        p = repo_root / rel
        if p.exists():
            canonical[rel] = p.read_text(encoding="utf-8")

    if not canonical:
        print(f"[chronicle] No canonical memory files found in {repo_root}")
        print(f"[chronicle] Expected one of: {', '.join(CANONICAL_FILES)}")
        sys.exit(1)

    now = datetime.now()
    synced_at = now.strftime("%A, %d-%m-%Y, %-I:%M ") + now.strftime("%p").lower()

    if not args.reverse:
        forward_sync(canonical, synced_at)

    if args.reverse or args.full:
        reverse_diff(canonical)


if __name__ == "__main__":
    main()
