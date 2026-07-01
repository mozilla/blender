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
import re
import sys
from dataclasses import dataclass

from github import Auth, GithubIntegration
from github.GithubException import UnknownObjectException
from github.PullRequest import PullRequest
from github.Repository import Repository

try:
    from scripts.config_utils import load_repo_config
    from scripts.github_utils import has_codeowner_approval, is_bot
except ImportError:
    from config_utils import load_repo_config  # type: ignore[no-redef]
    from github_utils import has_codeowner_approval, is_bot  # type: ignore[no-redef]

BOT_LOGIN = "mozilla-blender[bot]"

# Only process repos owned by these GitHub orgs/users.
# Any installation from an owner not on this list is ignored.
ALLOWED_OWNERS = frozenset({"mozilla", "mozilla-services", "mozilla-extensions"})

# Used to skip alerts that already have an investigated tag.
BLENDER_REPO = "mozilla/blender"
INVESTIGATED_TAG_PREFIX = "investigated/"
_INVESTIGATED_TAG_RE = re.compile(r"^investigated/(.+)/(\d+)$")

# Dependabot alert severities, ranked low to high. Used to skip alerts
# below a repo's configured investigate.severity_threshold.
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


AUTO_ENGINEER_LABEL = "blender:auto-engineer"
AUTO_ENGINEER_BRANCH_PREFIX = "blender/auto-engineer/"
PLAN_COMMIT_PREFIX = "BLEnder plan("


@dataclass
class Action:
    action: str  # "fix", "automerge", "investigate", or "auto-engineer"
    repo: str
    pr_number: int
    pr_title: str
    alert_number: int | None = None
    alert_package: str | None = None
    alert_ecosystem: str | None = None
    alert_severity: str | None = None
    alert_patched_version: str | None = None
    phase: str | None = None  # "plan", "implement", "self-review"
    issue_number: int | None = None
    issue_title: str | None = None
    trusted_author_associations: str | None = None
    forbidden_paths: str | None = None

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
        if self.phase is not None:
            d["phase"] = self.phase
            d["issue_number"] = self.issue_number
            d["issue_title"] = self.issue_title
            if self.trusted_author_associations:
                d["trusted_author_associations"] = self.trusted_author_associations
            if self.forbidden_paths:
                d["forbidden_paths"] = self.forbidden_paths
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


def _pr_has_implementation_commits(pr: PullRequest) -> bool:
    """True if the PR has commits beyond the initial plan commit."""
    commits = list(pr.get_commits())
    for c in commits:
        msg = c.commit.message or ""
        # Plan commits create/update .blender/plans/ files only.
        # Implementation commits have different messages.
        if not msg.startswith(PLAN_COMMIT_PREFIX):
            return True
    return False


def _has_comments_after_latest_commit(pr: PullRequest) -> bool:
    """True if non-bot comments exist after the latest commit date."""
    commits = list(pr.get_commits())
    latest_commit_date = max((c.commit.committer.date for c in commits), default=None)
    if latest_commit_date is None:
        return False
    for c in pr.get_issue_comments():
        if is_bot(c.user.login):
            continue
        if c.created_at >= latest_commit_date:
            return True
    for r in pr.get_reviews():
        if is_bot(r.user.login):
            continue
        if r.submitted_at and r.submitted_at >= latest_commit_date:
            return True
    return False


def _determine_pr_phase(pr: PullRequest) -> tuple[str | None, str]:
    """Determine what phase an auto-engineer PR needs next.

    Returns (phase, description) or (None, description) if no action needed.
    """
    has_impl = _pr_has_implementation_commits(pr)
    has_approval = has_codeowner_approval(pr)
    has_comments = _has_comments_after_latest_commit(pr)

    if not has_impl and has_approval:
        return "implement", "plan approved → implement"
    if not has_impl and has_comments:
        return "plan", "plan has feedback → address"
    if not has_impl:
        return None, "waiting for plan review"
    if has_impl and has_comments:
        return "implement", "implementation has feedback → address"
    return None, "waiting for code review"


def _has_bug_label(issue) -> bool:
    """True if the issue has a 'bug' label (case-insensitive)."""
    return any(label.name.lower() == "bug" for label in issue.labels)


def _is_trusted_author(issue, trusted_associations: set[str]) -> bool:
    """True if the issue author has a trusted association with the repo.

    Uses the author_association field from the GitHub Issues API.
    """
    association = getattr(issue, "author_association", None)
    if association is None:
        # PyGithub may not expose this; fall back to raw data
        raw = getattr(issue, "_rawData", {})
        association = raw.get("author_association", "NONE")
    return association in trusted_associations


def check_auto_engineer(repo: Repository, config: dict) -> list[Action]:
    """Check for auto-engineer work: issues to plan, PRs to advance."""
    ae_config = config.get("auto_engineer", {})
    if not ae_config.get("enabled", False):
        return []

    actions: list[Action] = []
    issue_label = ae_config.get("issue_label", "auto-engineer")
    trusted_str = ae_config.get("trusted_author_associations", "OWNER")
    trusted_associations = {s.strip() for s in trusted_str.split(",")}

    # Check for open PRs with the auto-engineer label
    open_prs = [
        pr
        for pr in repo.get_pulls(state="open")
        if any(label.name == AUTO_ENGINEER_LABEL for label in pr.labels)
    ]

    if open_prs:
        pr = open_prs[0]
        print(f"    Auto-engineer PR #{pr.number} exists")
        phase, description = _determine_pr_phase(pr)
        print(f"    PR #{pr.number}: {description}")
        if phase:
            issue_num = _issue_number_from_branch(pr.head.ref)
            actions.append(
                Action(
                    action="auto-engineer",
                    repo=repo.full_name,
                    pr_number=pr.number,
                    pr_title=pr.title,
                    phase=phase,
                    issue_number=issue_num,
                    issue_title=pr.title,
                )
            )
        return actions

    # Check recently merged PRs for self-review
    try:
        closed_prs = repo.get_pulls(state="closed", sort="updated", direction="desc")
        for pr in closed_prs:
            if not pr.merged:
                continue
            if not any(label.name == AUTO_ENGINEER_LABEL for label in pr.labels):
                continue
            if pr.merged_at is None:
                continue
            from datetime import datetime, timezone

            age = datetime.now(timezone.utc) - pr.merged_at
            if age.total_seconds() > 86400:
                break

            has_self_review = any(
                c.user.login == BOT_LOGIN
                and (c.body or "").startswith("## Self-Review")
                for c in pr.get_issue_comments()
            )
            if not has_self_review:
                print(f"    Merged PR #{pr.number}: needs self-review")
                issue_num = _issue_number_from_branch(pr.head.ref)
                actions.append(
                    Action(
                        action="auto-engineer",
                        repo=repo.full_name,
                        pr_number=pr.number,
                        pr_title=pr.title,
                        phase="self-review",
                        issue_number=issue_num,
                        issue_title=pr.title,
                    )
                )
                return actions
            break
    except Exception as e:
        print(f"    Error checking merged PRs: {e}")

    # No open or recent merged PR — look for issues to pick up
    existing_branches: set[str] = set()
    try:
        for branch in repo.get_branches():
            if branch.name.startswith(AUTO_ENGINEER_BRANCH_PREFIX):
                existing_branches.add(branch.name)
    except Exception:
        pass

    try:
        labeled_issues = list(repo.get_issues(state="open", labels=[issue_label]))
        labeled_issues = [i for i in labeled_issues if i.pull_request is None]
        labeled_issues = [i for i in labeled_issues if not i.assignees]
        # Only pick issues from trusted authors
        labeled_issues = [
            i for i in labeled_issues if _is_trusted_author(i, trusted_associations)
        ]
        labeled_issues = [
            i
            for i in labeled_issues
            if not any(
                b.startswith(f"{AUTO_ENGINEER_BRANCH_PREFIX}{i.number}-")
                for b in existing_branches
            )
        ]

        if labeled_issues:
            # Prefer newest bug-labeled issue, then newest of any type
            bugs = [i for i in labeled_issues if _has_bug_label(i)]
            issue = bugs[0] if bugs else labeled_issues[0]
            print(f"    Issue #{issue.number}: {issue.title} → plan")
            actions.append(
                Action(
                    action="auto-engineer",
                    repo=repo.full_name,
                    pr_number=0,
                    pr_title="",
                    phase="plan",
                    issue_number=issue.number,
                    issue_title=issue.title,
                )
            )
        else:
            # No labeled issues — let Claude pick from trusted open issues
            all_issues = list(repo.get_issues(state="open"))
            all_issues = [i for i in all_issues if i.pull_request is None]
            all_issues = [
                i for i in all_issues if _is_trusted_author(i, trusted_associations)
            ]
            if all_issues:
                print("    No labeled issues — Claude will pick from open issues")
                actions.append(
                    Action(
                        action="auto-engineer",
                        repo=repo.full_name,
                        pr_number=0,
                        pr_title="",
                        phase="plan",
                        issue_number=0,
                        issue_title="",
                    )
                )
    except Exception as e:
        print(f"    Error checking issues: {e}")

    return actions


def _issue_number_from_branch(branch: str) -> int:
    """Extract issue number from blender/auto-engineer/{number}-{slug}."""
    prefix = AUTO_ENGINEER_BRANCH_PREFIX
    if not branch.startswith(prefix):
        return 0
    rest = branch[len(prefix) :]
    parts = rest.split("-", 1)
    try:
        return int(parts[0])
    except (ValueError, IndexError):
        return 0


def process_repo(
    repo: Repository,
    investigated: set[tuple[str, int]] | None = None,
) -> list[Action]:
    """Check a single repo for actionable Dependabot PRs."""
    actions: list[Action] = []

    if not has_blender_config(repo):
        print("    No .blender/blender.yml, skipping")
        return actions

    repo_config = load_repo_config(repo)
    print("    Config found. Checking Dependabot PRs...")
    open_prs = list(repo.get_pulls(state="open"))
    dependabot_prs = [pr for pr in open_prs if pr.user.login == "dependabot[bot]"]

    # BLEnder bump PRs: must be from the BLEnder bot AND on the right branch.
    # Both conditions prevent an attacker from sneaking a PR into automerge.
    BLENDER_BOT_LOGIN = "mozilla-blender[bot]"
    blender_bump_prs = [
        pr
        for pr in open_prs
        if pr.user.login == BLENDER_BOT_LOGIN
        and pr.head.ref.startswith("blender/security-bump-")
    ]

    actionable_prs = dependabot_prs + blender_bump_prs

    if dependabot_prs:
        print(f"    Found {len(dependabot_prs)} Dependabot PR(s)")
    if blender_bump_prs:
        print(f"    Found {len(blender_bump_prs)} BLEnder bump PR(s)")

    for pr in actionable_prs:
        try:
            result = check_pr_status(repo, pr)
        except Exception as e:
            print(f"    PR #{pr.number}: error checking status: {e}")
            continue

        if result is None:
            print(f"    PR #{pr.number}: checks pending, skipping")
            continue

        if result == "fix":
            # A code-owner approval overrides all "already tried" guards.
            # This lets a code owner say "go ahead" and BLEnder retries.
            codeowner_approved = has_codeowner_approval(pr)
            if codeowner_approved:
                print(
                    f"    PR #{pr.number}: code owner approved — resetting fix guards"
                )

            # Check for BLEnder commits on the PR.
            # Only bot commits with the "BLEnder fix(" prefix count.
            # Non-bot commits use different messages and don't block dispatch.
            commits = pr.get_commits()
            has_blender_commit = any(
                (c.commit.message or "").startswith("BLEnder fix(") for c in commits
            )
            if has_blender_commit and not codeowner_approved:
                print(f"    PR #{pr.number}: BLEnder already committed a fix, skipping")
                continue

            # "Could not fix" is a permanent block — once posted, the PR
            # will not be retried unless a code owner approves.  Freshness
            # no longer matters; Dependabot rebases don't clear this guard.
            all_comments = list(pr.get_issue_comments())
            could_not_fix = any(
                c.user.login.endswith("[bot]")
                and (c.body or "").startswith("BLEnder could not fix")
                for c in all_comments
            )
            if could_not_fix and not codeowner_approved:
                print(
                    f"    PR #{pr.number}: BLEnder could not fix (permanent), skipping"
                )
                continue

            # Hard cap: count total fix attempts (BLEnder fix commits +
            # "could not fix" comments).  Prevents runaway LLM spend on
            # PRs that keep failing.
            fix_commit_count = sum(
                1
                for c in commits
                if (c.commit.message or "").startswith("BLEnder fix(")
            )
            could_not_fix_count = sum(
                1
                for c in all_comments
                if c.user.login.endswith("[bot]")
                and (c.body or "").startswith("BLEnder could not fix")
            )
            total_fix_attempts = fix_commit_count + could_not_fix_count
            max_attempts = repo_config.get("fix", {}).get("max_fix_attempts", 3)
            if total_fix_attempts >= max_attempts:
                print(
                    f"    PR #{pr.number}: hit max fix attempts "
                    f"({total_fix_attempts}/{max_attempts}), skipping"
                )
                continue

            # Fresh "picked up" comment means a fix is already in progress.
            latest_commit_date = max(
                (c.commit.committer.date for c in commits), default=None
            )
            if latest_commit_date is not None and not codeowner_approved:
                picked_up = any(
                    c.user.login.endswith("[bot]")
                    and (c.body or "").startswith("BLEnder picked up")
                    and c.created_at >= latest_commit_date
                    for c in all_comments
                )
                if picked_up:
                    print(
                        f"    PR #{pr.number}: fresh BLEnder picked-up comment, skipping"
                    )
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
        alert_actions = check_alerts(
            repo, investigated=investigated, config=repo_config
        )
        actions.extend(alert_actions)
    except Exception as e:
        print(f"    Error checking alerts: {e}")

    # Check for auto-engineer work
    try:
        ae_actions = check_auto_engineer(repo, repo_config)
        # Attach config settings that the workflow needs
        ae_config = repo_config.get("auto_engineer", {})
        for a in ae_actions:
            a.trusted_author_associations = ae_config.get(
                "trusted_author_associations", "OWNER"
            )
            a.forbidden_paths = ae_config.get(
                "forbidden_paths", ".github/ .env .circleci/"
            )
        actions.extend(ae_actions)
    except Exception as e:
        print(f"    Error checking auto-engineer: {e}")

    return actions


def fetch_investigated_alerts(
    integration: GithubIntegration,
) -> set[tuple[str, int]]:
    """Return (repo, alert_number) pairs already investigated.

    Reads lightweight tags on the blender repo. Each successful
    investigation creates a tag like ``investigated/{repo}/{number}``.
    One API call fetches all tags.
    """
    investigated: set[tuple[str, int]] = set()

    try:
        install = integration.get_repo_installation("mozilla", "blender")
        gh = integration.get_github_for_installation(install.id)
        repo = gh.get_repo(BLENDER_REPO)
        for tag in repo.get_tags():
            m = _INVESTIGATED_TAG_RE.match(tag.name)
            if m:
                investigated.add((m.group(1), int(m.group(2))))
    except Exception as e:
        print(f"  Warning: could not fetch investigated tags: {e}")

    print(f"  Found {len(investigated)} previously investigated alert(s)")
    return investigated


def check_alerts(
    repo: Repository,
    investigated: set[tuple[str, int]] | None = None,
    config: dict | None = None,
) -> list[Action]:
    """Check for open Dependabot security alerts and emit investigate actions.

    Uses PyGithub's raw requester because there is no built-in method
    for the Dependabot alerts API.

    Honors the repo's ``investigate`` config: skips entirely when
    ``enabled`` is false, and drops alerts below ``severity_threshold``.
    """
    actions: list[Action] = []

    inv_config = (config or {}).get("investigate", {})
    if not inv_config.get("enabled", True):
        print("    Investigate disabled for this repo, skipping alerts")
        return actions
    threshold = str(inv_config.get("severity_threshold", "") or "").lower()
    min_rank = SEVERITY_RANK.get(threshold, 0)

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

    # Fetch existing branches to prevent creating duplicates
    existing_branches: set[str] = set()
    try:
        for branch in repo.get_branches():
            if branch.name.startswith("blender/security/"):
                existing_branches.add(branch.name)
    except Exception:
        pass  # branch listing may fail; proceed without duplicate check

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

        # Skip alerts below the configured severity threshold
        if min_rank and SEVERITY_RANK.get(severity.lower(), 0) < min_rank:
            print(
                f"    Alert #{alert_number}: {severity} below "
                f"threshold {threshold}, skipping"
            )
            continue

        # Skip if a blender/security branch already exists for this alert
        branch_prefix = f"blender/security/{alert_number}-"
        if any(b.startswith(branch_prefix) for b in existing_branches):
            print(f"    Alert #{alert_number}: branch exists, skipping")
            continue

        # Skip if a successful investigate run already completed for this alert
        if investigated and (repo.full_name, alert_number) in investigated:
            print(f"    Alert #{alert_number}: already investigated, skipping")
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

    print("Checking previous investigate runs...")
    investigated = fetch_investigated_alerts(integration)

    print("Discovering installations...")
    install_repos = discover_repos(integration)

    for install_id, repos in install_repos:
        print(f"\nInstallation {install_id}: {len(repos)} repo(s)")

        for repo in repos:
            owner = repo.full_name.split("/")[0]
            if owner not in ALLOWED_OWNERS:
                print(f"\n  Skipping {repo.full_name} (owner not allowed)")
                continue
            print(f"\n  Checking {repo.full_name}...")
            try:
                actions.extend(process_repo(repo, investigated=investigated))
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
