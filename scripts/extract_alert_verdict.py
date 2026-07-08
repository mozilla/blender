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


def _iter_json_docs(log: str):
    """Yield parsed JSON documents from a Claude session log.

    Handles a single array (--output-format json), JSON-lines (a
    --verbose stream), and logs where non-JSON stderr noise is mixed in
    (e.g. a trust warning that `2>&1` merges into the file).
    """
    stripped = log.strip()
    if not stripped:
        return
    # Fast path: the whole log is one JSON document.
    try:
        yield json.loads(stripped)
        return
    except json.JSONDecodeError:
        pass
    # Fallback: parse each line that looks like JSON, skipping noise.
    for line in stripped.splitlines():
        line = line.strip()
        if not line or line[0] not in "[{":
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _extract_text_from_json_log(log: str) -> str:
    """Extract assistant and result text from Claude session logs."""
    parts = []
    for doc in _iter_json_docs(log):
        events = doc if isinstance(doc, list) else [doc]
        for event in events:
            if not isinstance(event, dict):
                continue
            # The final result event carries the last message text.
            if event.get("type") == "result" and isinstance(event.get("result"), str):
                parts.append(event["result"])
            msg = event.get("message")
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block["text"])
    return "\n".join(parts)


def _search_text(text: str) -> dict | None:
    """Search plain text for a VERDICT_JSON block or bare verdict object."""
    # Primary: look for ```VERDICT_JSON ... ``` fenced block
    m = re.search(r"```VERDICT_JSON\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            print("Extracted verdict from VERDICT_JSON block.")
            return obj
        except json.JSONDecodeError as e:
            print(f"VERDICT_JSON block found but invalid JSON: {e}", file=sys.stderr)

    # Fallback: any JSON object containing "affected" key
    for m2 in re.finditer(r"\{[^{}]*\"affected\"[^{}]*\}", text, re.DOTALL):
        try:
            obj = json.loads(m2.group())
            if "affected" in obj and "reason" in obj:
                print("Extracted verdict from JSON in output.")
                return obj
        except json.JSONDecodeError:
            continue

    return None


def extract(log: str) -> dict | None:
    """Try to extract verdict JSON from Claude's output text.

    Handles both plain-text output (-p) and JSON session logs
    (--output-format json) produced when CLAUDE_VERBOSE=true.
    """
    # Try plain text first (non-verbose mode)
    result = _search_text(log)
    if result:
        return result

    # Try JSON session log (verbose mode)
    text = _extract_text_from_json_log(log)
    if text:
        return _search_text(text)

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
