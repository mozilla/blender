#!/usr/bin/env python3
"""Post-investigation action for Dependabot security alerts.

Reads .blender-alert-verdict.json and takes the appropriate action:

  unaffected + dismiss enabled (low/medium) -> dismiss the alert via API
  unaffected + dismiss enabled (high/critical) -> no-op (require human review)
  unaffected + dismiss disabled -> no-op (suggest bumping the package)
  affected                      -> create advisory with private fork

Writes an HTML summary report to .blender-alert-summary.html for upload
as a workflow artifact (visible only to users with Actions access).

Environment variables:
  GH_TOKEN              -- GitHub token (required)
  REPO                  -- Target repo, e.g. mozilla/fx-private-relay (required)
  ALERT_NUMBER          -- Dependabot alert number (required)
  ALERT_PACKAGE         -- Package name (required)
  ALERT_ECOSYSTEM       -- Ecosystem, e.g. npm or pip (required)
  ALERT_SEVERITY        -- Alert severity (optional, for summary)
  ALERT_PATCHED_VERSION -- Version to bump to (optional)
  DRY_RUN               -- Set to "true" to skip mutations (default: false)
  DISMISS_UNAFFECTED    -- Set to "true" to dismiss unaffected alerts
"""

from __future__ import annotations

import json
import os
import sys
import time

from github import Auth, Github

from scripts.alert_report import write_summary

DISMISS_BLOCKED_SEVERITIES = {"critical", "high"}
VERDICT_FILE = ".blender-alert-verdict.json"
SUMMARY_FILE = ".blender-alert-summary.html"
REQUIRED_KEYS = {
    "affected",
    "confidence",
    "reason",
    "vulnerable_paths",
    "recommended_action",
}


def load_verdict() -> dict | None:
    """Load and validate the alert verdict file."""
    if not os.path.exists(VERDICT_FILE):
        print(f"No verdict file at {VERDICT_FILE}.")
        return None

    with open(VERDICT_FILE) as f:
        verdict = json.load(f)

    missing = REQUIRED_KEYS - set(verdict.keys())
    if missing:
        print(f"Verdict missing keys: {missing}")
        return None

    return verdict


def create_advisory_and_fork(
    repo,
    alert_number: int,
    package_name: str,
    dry_run: bool,
) -> tuple[str, str]:
    """Create a security advisory with a private fork.

    Returns (advisory_ghsa_id, fork_full_name) on success.
    """
    summary = f"Dependency security update for {package_name}"
    description = (
        f"Automated security update for Dependabot alert #{alert_number}. "
        f"See the advisory for details."
    )

    if dry_run:
        print(f"  DRY_RUN: would create advisory: {summary}")
        return ("", "")

    # Create advisory via raw API (PyGithub has no built-in method)
    url = f"/repos/{repo.full_name}/security-advisories"
    payload = {
        "summary": summary,
        "description": description,
        "severity": "low",
        "start_private_fork": True,
    }
    try:
        _, data = repo._requester.requestJsonAndCheck("POST", url, input=payload)
    except Exception as e:
        # Duplicate advisory returns 422
        error_str = str(e)
        if "422" in error_str or "already exists" in error_str.lower():
            print(f"  Advisory already exists for alert #{alert_number}, skipping.")
            return ("", "")
        raise

    ghsa_id = data.get("ghsa_id", "")
    print(f"  Created advisory {ghsa_id}")

    # Poll for private fork readiness (up to 5 minutes)
    fork_full_name = ""
    advisory_url = f"/repos/{repo.full_name}/security-advisories/{ghsa_id}"
    for attempt in range(10):
        time.sleep(min(30, 5 * (2**attempt)))
        _, advisory_data = repo._requester.requestJsonAndCheck("GET", advisory_url)
        forks = advisory_data.get("vulnerabilities", [])
        if forks:
            # The fork repo is in the advisory's fork field
            fork_info = advisory_data.get("private_fork", {})
            if fork_info:
                fork_full_name = fork_info.get("full_name", "")
                break
        # Also check top-level
        if advisory_data.get("private_fork"):
            fork_full_name = advisory_data["private_fork"].get("full_name", "")
            if fork_full_name:
                break

    if fork_full_name:
        print(f"  Private fork ready: {fork_full_name}")
    else:
        print("  Private fork not ready after polling. Remediate job may fail.")

    return (ghsa_id, fork_full_name)


def dismiss_alert(
    repo,
    alert_number: int,
    reason: str,
    dry_run: bool,
) -> None:
    """Dismiss a Dependabot alert as inaccurate (unaffected)."""
    if dry_run:
        print(f"  DRY_RUN: would dismiss alert #{alert_number}")
        return

    url = f"/repos/{repo.full_name}/dependabot/alerts/{alert_number}"
    payload = {
        "state": "dismissed",
        "dismissed_reason": "inaccurate",
        "dismissed_comment": f"BLEnder: {reason}",
    }
    repo._requester.requestJsonAndCheck("PATCH", url, input=payload)
    print(f"  Dismissed alert #{alert_number}")


def main() -> None:
    token = os.environ.get("GH_TOKEN", "")
    repo_name = os.environ.get("REPO", "")
    alert_number = int(os.environ.get("ALERT_NUMBER", "0"))
    package_name = os.environ.get("ALERT_PACKAGE", "unknown")
    severity = os.environ.get("ALERT_SEVERITY", "unknown")
    dry_run = os.environ.get("DRY_RUN", "false").lower() in ("true", "1", "yes")
    dismiss_enabled = os.environ.get("DISMISS_UNAFFECTED", "false").lower() in (
        "true",
        "1",
        "yes",
    )

    if not token or not repo_name:
        print("Error: GH_TOKEN and REPO are required.")
        sys.exit(1)

    if alert_number == 0:
        print("Error: ALERT_NUMBER is required.")
        sys.exit(1)

    g = Github(auth=Auth.Token(token))
    repo = g.get_repo(repo_name)

    verdict = load_verdict()
    if verdict is None:
        print("No valid verdict. Defaulting to no-op.")
        write_output("action", "noop")
        return

    affected = verdict.get("affected", False)
    recommended = verdict.get("recommended_action", "bump_pr")
    print(f"Verdict: affected={affected}, recommended={recommended}")
    print(f"  Reason: {verdict.get('reason', '(none)')}")

    reason = verdict.get("reason", "(none)")

    if not affected:
        if dismiss_enabled and severity.lower() not in DISMISS_BLOCKED_SEVERITIES:
            print("  Unaffected + dismiss enabled. Dismissing alert.")
            dismiss_alert(repo, alert_number, reason, dry_run)
            action = "dismissed"
        elif dismiss_enabled:
            print(
                f"  Unaffected but severity is {severity}."
                " Recommend manual review before dismissing."
            )
            action = "noop"
        else:
            print("  Unaffected + dismiss disabled. Consider bumping the package.")
            action = "noop"
        write_output("action", action)
    else:
        print("  Affected. Creating advisory and private fork.")
        ghsa_id, fork_repo = create_advisory_and_fork(
            repo,
            alert_number,
            package_name,
            dry_run,
        )
        action = "private_fork"
        write_output("action", action)
        write_output("advisory_ghsa_id", ghsa_id)
        write_output("fork_repo", fork_repo)

    write_summary(
        SUMMARY_FILE, repo_name, alert_number, package_name, severity, action, verdict
    )


def write_output(key: str, value: str) -> None:
    """Write a key=value pair to $GITHUB_OUTPUT."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"  output: {key}={value}")


if __name__ == "__main__":
    main()
