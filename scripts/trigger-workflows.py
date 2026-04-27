#!/usr/bin/env python3
"""Trigger fix or automerge workflows from sweep output.

Reads a JSON array of actions from the SWEEP_ACTIONS env var and
triggers the appropriate GitHub workflow for each one via `gh`.

Automerge workflows handle all eligible PRs in a single run, so
we deduplicate and trigger once per repo. Fix workflows are
triggered once per PR.

Environment variables:
  SWEEP_ACTIONS -- JSON array from sweep.py output (required)
  GH_TOKEN      -- GitHub token for `gh workflow run` (required)
"""

from __future__ import annotations

import json
import os
import subprocess
import time

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

WORKFLOW_MAP = {
    "fix": "fix-dependabot-pr.yml",
    "automerge": "chore-automerge-dependabot-prs.yml",
}


def trigger_workflow(cmd: list[str], label: str) -> bool:
    """Run a gh workflow command with retries. Returns True on success."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            subprocess.run(cmd, check=True)
            return True
        except subprocess.CalledProcessError as e:
            if attempt < MAX_RETRIES:
                print(f"  Attempt {attempt} failed, retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"  Failed after {MAX_RETRIES} attempts: {e}")
    return False


def main() -> None:
    raw = os.environ.get("SWEEP_ACTIONS", "[]")
    actions = json.loads(raw)

    if not actions:
        print("No actions to trigger.")
        return

    print(f"Actions from sweep ({len(actions)}):")
    for a in actions:
        print(f"  {a['action']} -> {a['repo']} PR #{a['pr_number']}")

    # Deduplicate automerge: one trigger per repo
    automerge_repos: set[str] = set()
    fix_actions = []
    for a in actions:
        if a["action"] == "automerge":
            automerge_repos.add(a["repo"])
        elif a["action"] == "fix":
            fix_actions.append(a)
        else:
            print(f"Unknown action: {a['action']}")

    failures = 0

    # Trigger automerge once per repo
    for repo in sorted(automerge_repos):
        workflow = WORKFLOW_MAP["automerge"]
        cmd = [
            "gh",
            "workflow",
            "run",
            workflow,
            "-f",
            f"target_repo={repo}",
            "-f",
            "dry_run=false",
        ]
        print(f"Triggering {workflow} for {repo} (all eligible PRs)")
        if not trigger_workflow(cmd, f"automerge {repo}"):
            failures += 1

    # Trigger fix once per PR
    for a in fix_actions:
        workflow = WORKFLOW_MAP["fix"]
        cmd = [
            "gh",
            "workflow",
            "run",
            workflow,
            "-f",
            f"target_repo={a['repo']}",
            "-f",
            "dry_run=false",
            "-f",
            f"pr_number={a['pr_number']}",
        ]
        print(f"Triggering {workflow} for {a['repo']} PR #{a['pr_number']}")
        if not trigger_workflow(cmd, f"fix {a['repo']} #{a['pr_number']}"):
            failures += 1

    if failures:
        print(f"\n{failures} trigger(s) failed.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
