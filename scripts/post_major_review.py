#!/usr/bin/env python3
"""BLEnder post-major-review: read Claude's verdict and act on it.

This script has GH_TOKEN but does NOT have ANTHROPIC_API_KEY.
It reads .blender-verdict.json written by Claude.

Actions:
  safe + high/medium confidence -> approve PR, enable auto-merge, post comment
  not safe or low confidence    -> post detailed skip comment
  no verdict file               -> post fallback comment

Environment variables:
  PR_NUMBER  -- PR number (required)
  REPO       -- GitHub repo, e.g. mozilla/fx-private-relay (required)
  GH_TOKEN   -- GitHub token with pull-requests:write (required)
  DRY_RUN    -- Set to "true" to skip approval/merge (default: false)
"""

from __future__ import annotations

import json
import os
import sys

from github import Auth, Github
from github.PullRequest import PullRequest

VERDICT_FILE = ".blender-verdict.json"


def _enable_auto_merge(pr: PullRequest) -> None:
    """Enable auto-merge on a PR via the GraphQL API."""
    query = """
    mutation EnableAutoMerge($prId: ID!) {
      enablePullRequestAutoMerge(input: {pullRequestId: $prId, mergeMethod: SQUASH}) {
        pullRequest { autoMergeRequest { enabledAt } }
      }
    }
    """
    _, data = pr._requester.requestJsonAndCheck(
        "POST",
        "/graphql",
        input={"query": query, "variables": {"prId": pr.node_id}},
    )
    errors = data.get("errors")
    if errors:
        msg = "; ".join(e.get("message", str(e)) for e in errors)
        raise RuntimeError(f"GraphQL enablePullRequestAutoMerge failed: {msg}")


def post_comment(pr: PullRequest, body: str, dry_run: bool) -> None:
    if dry_run:
        print(f"DRY_RUN: would comment:\n{body}")
        return
    pr.create_issue_comment(body)


def approve_and_merge(pr: PullRequest, confidence: str, dry_run: bool) -> None:
    """Approve the PR and enable auto-merge."""
    review_body = (
        f"BLEnder auto-merge: major bump evaluated as safe ({confidence} confidence)."
    )
    if dry_run:
        print("DRY_RUN: would approve and enable auto-merge")
        return
    pr.create_review(event="APPROVE", body=review_body)
    _enable_auto_merge(pr)


def main() -> None:
    pr_number = os.environ.get("PR_NUMBER", "")
    repo_name = os.environ.get("REPO", "")
    token = os.environ.get("GH_TOKEN", "")
    dry_run = os.environ.get("DRY_RUN", "false").lower() in ("true", "1", "yes")

    if not all([pr_number, repo_name, token]):
        print("Error: PR_NUMBER, REPO, and GH_TOKEN are required.")
        sys.exit(1)

    gh = Github(auth=Auth.Token(token))
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(int(pr_number))

    # No verdict file: Claude failed or timed out
    if not os.path.exists(VERDICT_FILE):
        print("No verdict file found. Claude could not evaluate this bump.")
        post_comment(
            pr,
            "BLEnder: could not evaluate this major version bump. Manual review needed.",
            dry_run,
        )
        return

    # Parse verdict
    print(f"Reading verdict from {VERDICT_FILE}...")
    try:
        with open(VERDICT_FILE) as f:
            verdict = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error reading verdict: {exc}")
        post_comment(
            pr,
            "BLEnder: verdict file was malformed. Manual review needed.",
            dry_run,
        )
        return

    safe = verdict.get("safe", False)
    confidence = verdict.get("confidence", "low")
    reason = verdict.get("reason", "No reason provided")
    breaking_changes = "; ".join(verdict.get("breaking_changes", []))
    affected_code = "; ".join(verdict.get("affected_code", []))
    test_coverage = verdict.get("test_coverage", "Unknown")

    print(f"Verdict: safe={safe} confidence={confidence}")
    print(f"Reason: {reason}")

    if safe and confidence != "low":
        comment = (
            "BLEnder: major version bump is safe to merge.\n\n"
            f"**Confidence:** {confidence}\n"
            f"**Reason:** {reason}\n\n"
            f"**Breaking changes:** "
            f"{breaking_changes or 'None that affect this codebase'}\n"
            f"**Test coverage:** {test_coverage}"
        )
        approve_and_merge(pr, confidence, dry_run)
        post_comment(pr, comment, dry_run)
        if not dry_run:
            print("Done. PR approved and auto-merge enabled.")
    else:
        comment = (
            "BLEnder: this major version bump needs human review.\n\n"
            f"**Confidence:** {confidence}\n"
            f"**Reason:** {reason}\n\n"
            f"**Breaking changes:** {breaking_changes or 'None identified'}\n"
            f"**Affected code:** {affected_code or 'None identified'}\n"
            f"**Test coverage:** {test_coverage}"
        )
        post_comment(pr, comment, dry_run)
        if not dry_run:
            print("Posted analysis comment for human review.")


if __name__ == "__main__":
    main()
