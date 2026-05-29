#!/usr/bin/env python3
"""Extract fenced blocks (PLAN_MD, SELF_REVIEW_MD) from Claude's output.

Claude runs in a sandbox that prevents file writes.  Instead, the prompt
tells Claude to output a fenced block with a specific label.  This script
parses that block and writes it to a file.

Usage: extract_plan.py <claude_log_file> <block_label> <output_file>

Examples:
  extract_plan.py claude.log PLAN_MD .blender-plan.md
  extract_plan.py claude.log SELF_REVIEW_MD .blender-self-review.md
"""

import json
import re
import sys


def _extract_text_from_json_log(log: str) -> str:
    """Extract assistant text from --output-format json session logs."""
    try:
        events = json.loads(log)
    except (json.JSONDecodeError, TypeError):
        return ""

    if not isinstance(events, list):
        return ""

    parts = []
    for event in events:
        msg = event.get("message") if isinstance(event, dict) else None
        if not msg or msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
    return "\n".join(parts)


def _search_text(text: str, label: str) -> str | None:
    """Search for a fenced block with the given label."""
    pattern = rf"```{re.escape(label)}\s*\n(.*?)\n\s*```"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def extract(log: str, label: str) -> str | None:
    """Extract a labeled fenced block from Claude's output.

    Handles both plain-text output (-p) and JSON session logs
    (--output-format json) produced when CLAUDE_VERBOSE=true.
    """
    result = _search_text(log, label)
    if result:
        return result

    text = _extract_text_from_json_log(log)
    if text:
        return _search_text(text, label)

    return None


def main() -> None:
    if len(sys.argv) < 4:
        print(
            "Usage: extract_plan.py <claude_log_file> <block_label> <output_file>",
            file=sys.stderr,
        )
        sys.exit(1)

    log_path = sys.argv[1]
    label = sys.argv[2]
    output_path = sys.argv[3]

    try:
        with open(log_path) as f:
            log = f.read()
    except OSError as e:
        print(f"Cannot read log file: {e}", file=sys.stderr)
        sys.exit(1)

    content = extract(log, label)
    if content is None:
        print(f"No {label} block found in Claude output.", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "w") as f:
        f.write(content)
        f.write("\n")

    print(f"Extracted {label} block ({len(content)} chars) to {output_path}")


if __name__ == "__main__":
    main()
