"""Shared GitHub utilities for BLEnder scripts."""

from __future__ import annotations

from github.PullRequest import PullRequest


def enable_auto_merge(pr: PullRequest) -> None:
    """Enable auto-merge on a PR via the GraphQL API.

    The REST API merge endpoint requires elevated permissions that
    GITHUB_TOKEN in Actions doesn't have with branch protection.
    The GraphQL enablePullRequestAutoMerge mutation works with the
    standard token and lets GitHub merge once protection rules pass.
    """
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
