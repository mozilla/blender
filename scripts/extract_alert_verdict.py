#!/usr/bin/env python3
"""Extract alert verdict JSON from Claude's text output.

Claude runs in a sandbox that prevents file writes.  Instead, the prompt
tells Claude to output a ```VERDICT_JSON fenced block.  This script
parses that block and writes .blender-alert-verdict.json.

Usage: extract_alert_verdict.py <claude_log_file>
"""

import json
import re
import sys

VERDICT_FILE = ".blender-alert-verdict.json"


def extract(log: str) -> dict | None:
    """Try to extract verdict JSON from Claude's output text."""
    # Primary: look for ```VERDICT_JSON ... ``` fenced block
    m = re.search(r"```VERDICT_JSON\s*\n(.*?)\n\s*```", log, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            print("Extracted verdict from VERDICT_JSON block.")
            return obj
        except json.JSONDecodeError as e:
            print(f"VERDICT_JSON block found but invalid JSON: {e}", file=sys.stderr)

    # Fallback: any JSON object containing "affected" key
    for m2 in re.finditer(r"\{[^{}]*\"affected\"[^{}]*\}", log, re.DOTALL):
        try:
            obj = json.loads(m2.group())
            if "affected" in obj and "reason" in obj:
                print("Extracted verdict from JSON in output.")
                return obj
        except json.JSONDecodeError:
            continue

    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: extract_alert_verdict.py <claude_log_file>", file=sys.stderr)
        sys.exit(1)

    log_path = sys.argv[1]
    try:
        with open(log_path) as f:
            log = f.read()
    except OSError as e:
        print(f"Cannot read log file: {e}", file=sys.stderr)
        sys.exit(1)

    verdict = extract(log)
    if verdict is None:
        print("No verdict found in Claude output.", file=sys.stderr)
        sys.exit(1)

    with open(VERDICT_FILE, "w") as f:
        json.dump(verdict, f, indent=2)


if __name__ == "__main__":
    main()
