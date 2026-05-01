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

try:
    from scripts.github_utils import Verdict, enable_auto_merge, has_blender_verdict
except ModuleNotFoundError:
    from github_utils import Verdict, enable_auto_merge, has_blender_verdict

VERDICT_FILE = ".blender-verdict.json"


def post_comment(pr: PullRequest, body: str, dry_run: bool) -> None:
    if dry_run:
        print(f"DRY_RUN: would comment:\n{body}")
        return
    if has_blender_verdict(pr):
        print("Verdict comment already exists, skipping duplicate.")
        return
    pr.create_issue_comment(body)


def approve_and_merge(pr: PullRequest, confidence: str, dry_run: bool) -> str | None:
    """Approve the PR and enable auto-merge.

    Returns None on success, or an error message if auto-merge failed.
    The approval is posted regardless.
    """
    review_body = Verdict.APPROVED.comment(f"({confidence} confidence).")
    if dry_run:
        print("DRY_RUN: would approve and enable auto-merge")
        return None
    pr.create_review(event="APPROVE", body=review_body)
    return enable_auto_merge(pr)


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
            Verdict.NO_VERDICT.comment("— manual review needed."),
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
            Verdict.MALFORMED.comment("— manual review needed."),
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
        merge_err = approve_and_merge(pr, confidence, dry_run)
        auto_merge_note = ""
        if merge_err:
            print(f"Warning: auto-merge failed: {merge_err}")
            auto_merge_note = (
                "\n\n> **Note:** auto-merge could not be enabled"
                f" ({merge_err}).\n"
                "> A maintainer can merge this PR manually, or"
                " [enable auto-merge](https://docs.github.com/en/"
                "repositories/configuring-branches-and-merges-in-"
                "your-repository/configuring-pull-request-merges/"
                "managing-auto-merge-for-pull-requests-in-your-"
                "repository) on the repo so BLEnder can merge"
                " safe updates in the future."
            )
        comment = (
            f"{Verdict.SAFE.comment('to merge.')}\n\n"
            f"**Confidence:** {confidence}\n"
            f"**Reason:** {reason}\n\n"
            f"**Breaking changes:** "
            f"{breaking_changes or 'None that affect this codebase'}\n"
            f"**Test coverage:** {test_coverage}"
            f"{auto_merge_note}"
        )
        post_comment(pr, comment, dry_run)
        if not dry_run:
            if merge_err:
                print("Done. PR approved. Auto-merge not available.")
            else:
                print("Done. PR approved and auto-merge enabled.")
    else:
        comment = (
            f"{Verdict.NEEDS_REVIEW.comment()}\n\n"
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
