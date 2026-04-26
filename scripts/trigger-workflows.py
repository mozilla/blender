#!/usr/bin/env python3
"""Trigger fix or automerge workflows from sweep output.

Reads a JSON array of actions from the SWEEP_ACTIONS env var and
triggers the appropriate GitHub workflow for each one via `gh`.

Environment variables:
  SWEEP_ACTIONS -- JSON array from sweep.py output (required)
  GH_TOKEN      -- GitHub token for `gh workflow run` (required)
"""

from __future__ import annotations

import json
import os
import subprocess


WORKFLOW_MAP = {
    "fix": "fix-dependabot-pr.yml",
    "automerge": "chore-automerge-dependabot-prs.yml",
}


def main() -> None:
    raw = os.environ.get("SWEEP_ACTIONS", "[]")
    actions = json.loads(raw)

    if not actions:
        print("No actions to trigger.")
        return

    print(f"Actions to trigger ({len(actions)}):")
    for a in actions:
        print(f"  {a['action']} -> {a['repo']} PR #{a['pr_number']}")

    failures = 0
    for a in actions:
        repo = a["repo"]
        pr = a["pr_number"]
        action = a["action"]

        workflow = WORKFLOW_MAP.get(action)
        if not workflow:
            print(f"Unknown action: {action}")
            failures += 1
            continue

        fields = ["-f", f"target_repo={repo}", "-f", "dry_run=false"]
        if action == "fix":
            fields += ["-f", f"pr_number={pr}"]

        cmd = ["gh", "workflow", "run", workflow] + fields
        print(f"Triggering {workflow} for {repo} PR #{pr}")
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"  Failed to trigger: {e}")
            failures += 1

    if failures:
        print(f"\n{failures} trigger(s) failed.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
