#!/usr/bin/env python3
"""BLEnder sweep: discover repos and check for work.

Authenticates as the BLEnder GitHub App, lists all installations,
finds repos with .blender/blender.yml, checks open Dependabot PRs,
and outputs JSON describing what actions to take.

Environment variables:
  BLENDER_APP_ID          -- GitHub App ID (required)
  BLENDER_APP_PRIVATE_KEY -- GitHub App private key PEM (required)
  DRY_RUN                 -- Set to "true" to skip triggering workflows (default: false)

Output: JSON array of action objects, one per PR:
  [
    {
      "action": "fix" | "automerge",
      "repo": "owner/name",
      "pr_number": 123,
      "pr_title": "..."
    }
  ]
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

from github import Auth, GithubIntegration
from github.GithubException import UnknownObjectException
from github.PullRequest import PullRequest
from github.Repository import Repository


@dataclass
class Action:
    action: str  # "fix", "automerge", or "investigate"
    repo: str
    pr_number: int
    pr_title: str
    alert_number: int | None = None
    alert_package: str | None = None
    alert_ecosystem: str | None = None
    alert_severity: str | None = None
    alert_patched_version: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "action": self.action,
            "repo": self.repo,
            "pr_number": self.pr_number,
            "pr_title": self.pr_title,
        }
        if self.alert_number is not None:
            d["alert_number"] = self.alert_number
            d["alert_package"] = self.alert_package
            d["alert_ecosystem"] = self.alert_ecosystem
            d["alert_severity"] = self.alert_severity
            d["alert_patched_version"] = self.alert_patched_version
        return d


def has_blender_config(repo: Repository) -> bool:
    """Check if a repo has .blender/blender.yml."""
    try:
        repo.get_contents(".blender/blender.yml")
        return True
    except UnknownObjectException:
        return False


def check_pr_status(repo: Repository, pr: PullRequest) -> str | None:
    """Check CI status for a PR. Returns 'fix', 'automerge', or None.

    - All checks pass -> 'automerge'
    - Any check fails -> 'fix'
    - Checks still pending -> None (skip this run)
    """
    commit = repo.get_commit(pr.head.sha)

    failing = 0
    pending = 0

    for check in commit.get_check_runs():
        if check.status != "completed":
            pending += 1
        elif check.conclusion not in ("success", "skipped", "neutral"):
            failing += 1

    combined_status = commit.get_combined_status()
    for status in combined_status.statuses:
        if status.state in ("failure", "error"):
            failing += 1
        elif status.state == "pending":
            pending += 1

    if failing > 0:
        return "fix"
    if pending > 0:
        return None
    return "automerge"


def discover_repos(
    integration: GithubIntegration,
) -> list[tuple[int, list[Repository]]]:
    """List all installations and their repos."""
    results = []
    for installation in integration.get_installations():
        repos = list(installation.get_repos())
        results.append((installation.id, repos))
    return results


def process_repo(repo: Repository) -> list[Action]:
    """Check a single repo for actionable Dependabot PRs."""
    actions: list[Action] = []

    if not has_blender_config(repo):
        print("    No .blender/blender.yml, skipping")
        return actions

    print("    Config found. Checking Dependabot PRs...")
    open_prs = repo.get_pulls(state="open")
    dependabot_prs = [pr for pr in open_prs if pr.user.login == "dependabot[bot]"]

    if not dependabot_prs:
        print("    No open Dependabot PRs")
        return actions

    print(f"    Found {len(dependabot_prs)} Dependabot PR(s)")

    for pr in dependabot_prs:
        try:
            result = check_pr_status(repo, pr)
        except Exception as e:
            print(f"    PR #{pr.number}: error checking status: {e}")
            continue

        if result is None:
            print(f"    PR #{pr.number}: checks pending, skipping")
            continue

        if result == "fix":
            # Check for BLEnder commits on the PR.
            # Only bot commits with the "BLEnder fix(" prefix count.
            # Human commits use different messages and don't block dispatch.
            commits = pr.get_commits()
            has_blender_commit = any(
                (c.commit.message or "").startswith("BLEnder fix(") for c in commits
            )
            if has_blender_commit:
                print(f"    PR #{pr.number}: BLEnder already committed a fix, skipping")
                continue

            # Only skip if a bot fix-related comment was posted AFTER the
            # latest commit.  Human comments are ignored (login must end
            # with "[bot]").  Stale comments (before a force-push) are
            # also ignored so the fix can be retried on new code.
            latest_commit_date = max(
                (c.commit.committer.date for c in commits), default=None
            )
            if latest_commit_date is not None:
                fix_comments = [
                    c
                    for c in pr.get_issue_comments()
                    if c.user.login.endswith("[bot]")
                    and (
                        (c.body or "").startswith("BLEnder picked up")
                        or (c.body or "").startswith("BLEnder could not fix")
                    )
                ]
                fresh_fix_comment = any(
                    c.created_at >= latest_commit_date for c in fix_comments
                )
                if fresh_fix_comment:
                    print(f"    PR #{pr.number}: fresh BLEnder fix comment, skipping")
                    continue

        print(f"    PR #{pr.number}: {result}")
        actions.append(
            Action(
                action=result,
                repo=repo.full_name,
                pr_number=pr.number,
                pr_title=pr.title,
            )
        )

    # Check Dependabot security alerts
    try:
        alert_actions = check_alerts(repo)
        actions.extend(alert_actions)
    except Exception as e:
        print(f"    Error checking alerts: {e}")

    return actions


def check_alerts(repo: Repository) -> list[Action]:
    """Check for open Dependabot security alerts and emit investigate actions.

    Uses PyGithub's raw requester because there is no built-in method
    for the Dependabot alerts API.
    """
    actions: list[Action] = []

    url = f"/repos/{repo.full_name}/dependabot/alerts"
    try:
        headers, data = repo._requester.requestJsonAndCheck(
            "GET", url, parameters={"state": "open", "per_page": "100"}
        )
    except Exception as e:
        print(f"    Could not fetch alerts: {e}")
        return actions

    if not data:
        print("    No open Dependabot alerts")
        return actions

    print(f"    Found {len(data)} open Dependabot alert(s)")

    # Fetch existing branches for dedup
    existing_branches: set[str] = set()
    try:
        for branch in repo.get_branches():
            if branch.name.startswith("blender/security/"):
                existing_branches.add(branch.name)
    except Exception:
        pass  # branch listing may fail; proceed without dedup

    for alert in data:
        alert_number = alert.get("number")
        vuln = alert.get("security_vulnerability", {})
        pkg = vuln.get("package", {})
        advisory = alert.get("security_advisory", {})
        package_name = pkg.get("name", "unknown")
        ecosystem = pkg.get("ecosystem", "unknown")
        severity = advisory.get("severity", "unknown")
        patched = vuln.get("first_patched_version", {})
        patched_version = patched.get("identifier", "") if patched else ""

        # Skip if a blender/security branch already exists for this alert
        branch_prefix = f"blender/security/{alert_number}-"
        if any(b.startswith(branch_prefix) for b in existing_branches):
            print(f"    Alert #{alert_number}: branch exists, skipping")
            continue

        print(f"    Alert #{alert_number}: {package_name} ({severity})")
        actions.append(
            Action(
                action="investigate",
                repo=repo.full_name,
                pr_number=0,
                pr_title=f"Security alert: {package_name}",
                alert_number=alert_number,
                alert_package=package_name,
                alert_ecosystem=ecosystem,
                alert_severity=severity,
                alert_patched_version=patched_version,
            )
        )

    return actions


def sweep(app_id: str, private_key: str) -> list[Action]:
    """Run the sweep. Returns a list of actions to take."""
    auth = Auth.AppAuth(int(app_id), private_key)
    integration = GithubIntegration(auth=auth)

    actions: list[Action] = []

    print("Discovering installations...")
    install_repos = discover_repos(integration)

    for install_id, repos in install_repos:
        print(f"\nInstallation {install_id}: {len(repos)} repo(s)")

        for repo in repos:
            print(f"\n  Checking {repo.full_name}...")
            try:
                actions.extend(process_repo(repo))
            except Exception as e:
                print(f"    Error processing {repo.full_name}: {e}")
                continue

    return actions


def main() -> None:
    app_id = os.environ.get("BLENDER_APP_ID", "")
    private_key = os.environ.get("BLENDER_APP_PRIVATE_KEY", "")
    dry_run = os.environ.get("DRY_RUN", "false").lower() in ("true", "1", "yes")

    if not app_id:
        print("Error: BLENDER_APP_ID is required.")
        sys.exit(1)
    if not private_key:
        print("Error: BLENDER_APP_PRIVATE_KEY is required.")
        sys.exit(1)

    actions = sweep(app_id, private_key)

    print(f"\n=== Sweep complete: {len(actions)} action(s) ===")
    output = [a.to_dict() for a in actions]
    output_json = json.dumps(output)

    if dry_run:
        print("DRY_RUN: would trigger:")
        for a in actions:
            print(f"  {a.action} -> {a.repo} PR #{a.pr_number}")

    # Write to $GITHUB_OUTPUT for the workflow to consume
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"actions={output_json}\n")

    # Also write to stdout for logging
    print(f"actions={output_json}")


if __name__ == "__main__":
    main()
