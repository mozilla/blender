"""Shared GitHub utilities for BLEnder scripts."""

from __future__ import annotations

from enum import Enum

from github.PullRequest import PullRequest


BOT_LOGIN = "mozilla-blender[bot]"


class Verdict(Enum):
    """Review verdict codes and their comment messages.

    The enum *name* (e.g. ``SAFE``) is the stable tag written at the
    start of every comment.  Dedup checks match on ``"SAFE:"``, so
    changing a name is a breaking change.  The *value* is the human-
    readable message that follows the tag.
    """

    SAFE = "major version bump is safe"
    NEEDS_REVIEW = "this major version bump needs human review"
    NO_VERDICT = "could not evaluate this major version bump"
    MALFORMED = "verdict file was malformed"
    APPROVED = "auto-merge: major bump evaluated as safe"

    def comment(self, detail: str = "") -> str:
        """Build a comment string: ``TAG: message [detail]``."""
        text = f"{self.name}: {self.value}"
        if detail:
            text = f"{text} {detail}"
        return text

    @classmethod
    def tags(cls) -> tuple[str, ...]:
        """All verdict tag prefixes (e.g. ``"SAFE:"``) for matching."""
        return tuple(f"{v.name}:" for v in cls)


def has_blender_verdict(pr: PullRequest) -> bool:
    """True if BLEnder already posted a review verdict on this PR."""
    tags = Verdict.tags()
    for c in pr.get_issue_comments():
        if c.user.login != BOT_LOGIN:
            continue
        if any(c.body.startswith(t) for t in tags):
            return True
    for r in pr.get_reviews():
        if (
            r.user.login == BOT_LOGIN
            and r.body
            and any(r.body.startswith(t) for t in tags)
        ):
            return True
    return False


def enable_auto_merge(pr: PullRequest) -> str | None:
    """Enable auto-merge on a PR via the GraphQL API.

    Returns None on success, or an error message string on failure.

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
        return "; ".join(e.get("message", str(e)) for e in errors)
    return None
