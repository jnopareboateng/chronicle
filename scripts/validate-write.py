#!/usr/bin/env python3
"""chronicle: PreToolUse hook — validate memory file writes.

Blocks any write where the Last Updated: timestamp fails the canonical format.
Advisory warning (exit 1) when the header is being removed.
Pass-through (exit 0) for non-memory files or writes that don't touch the header.

Claude Code passes hook context as JSON on stdin:
  {"tool_name": "Write"|"Edit", "tool_input": {...}}
"""
import json
import re
import sys
from pathlib import Path

TIMESTAMP_RE = re.compile(
    r"^Last Updated: [A-Za-z]+, \d{2}-\d{2}-\d{4}, \d{1,2}:\d{2} (?:am|pm)"
)
MEMORY_NAMES = {"PROJECT_MEMORY.md", "UPDATE_LOG.md", "PHASE_STATUS.md"}


def is_memory_file(path: str) -> bool:
    p = Path(path)
    if p.name in MEMORY_NAMES:
        return True
    normalized = path.replace("\\", "/")
    return "docs/memory" in normalized and p.suffix == ".md"


def find_last_updated(text: str) -> str | None:
    for line in text.splitlines()[:10]:
        if line.startswith("Last Updated:"):
            return line
    return None


def validate_text(text: str, file_name: str) -> None:
    """Exit 2 (block) if Last Updated: is present but malformed."""
    line = find_last_updated(text)
    if line is None:
        return  # no header — partial edit or new file, allow

    if not TIMESTAMP_RE.match(line):
        bad = line[len("Last Updated: "):]
        print(
            f"[chronicle] BLOCKED: bad timestamp in {file_name}\n"
            f"  Found:    '{bad}'\n"
            f"  Expected: 'Day, DD-MM-YYYY, H:MM am/pm'  (e.g. 'Tuesday, 24-06-2026, 3:15 pm')\n\n"
            f"  Fix — run this and use the output verbatim:\n"
            f"    python3 ~/.claude/plugins/chronicle/scripts/timestamp.py\n"
            f"    # or in DocinaBox: python3 scripts/agent_harness/current_timestamp.py"
        )
        sys.exit(2)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    tip = data.get("tool_input", {})
    path = tip.get("file_path", "")

    if not path or not is_memory_file(path):
        sys.exit(0)

    name = Path(path).name

    if tool == "Write":
        validate_text(tip.get("content", ""), name)

    elif tool == "Edit":
        new_s = tip.get("new_string", "")
        old_s = tip.get("old_string", "")
        if "Last Updated:" in new_s:
            validate_text(new_s, name)
        elif "Last Updated:" in old_s:
            # Removing the header — advisory only
            print(
                f"[chronicle] WARNING: {name} — this edit removes the Last Updated: header.\n"
                f"  Memory files must keep this line. Add it back with a fresh timestamp."
            )
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
