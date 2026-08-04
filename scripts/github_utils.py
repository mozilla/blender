"""Shared GitHub utilities for BLEnder scripts."""

from __future__ import annotations

from enum import Enum

from github.PullRequest import PullRequest


BOT_LOGIN = "mozilla-blender[bot]"


def is_bot(login: str) -> bool:
    """True if the login belongs to a bot account.

    GitHub enforces the ``name[bot]`` convention for App and bot
    accounts — this is a platform invariant, not a heuristic.
    """
    return login.endswith("[bot]")


class Verdict(Enum):
    """Review verdict codes and their comment messages.

    The enum *name* (e.g. ``SAFE``) is the stable tag written at the
    start of every comment.  Dedup checks match on ``"SAFE:"``, so
    changing a name is a breaking change.  The *value* is the
    readable message that follows the tag.
    """

    SAFE = "major version bump is safe"
    NEEDS_REVIEW = "this major version bump needs code-owner review"
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


def has_codeowner_approval(pr: PullRequest) -> bool:
    """True if a code owner approved this PR.

    Used to detect when a code owner overrides a BLEnder NEEDS_REVIEW
    verdict, signaling that the major bump should proceed.

    CODEOWNERS enforcement is handled by GitHub branch protection,
    not here.  If the repo's branch protection requires code-owner
    review (per the AI-in-dev policy), GitHub only counts approvals
    from designated code owners.  A non-bot APPROVED review on a
    protected branch therefore implies the reviewer is a code owner.

    We filter out bot accounts (logins ending with ``[bot]``) because
    GitHub App and bot accounts always follow the ``name[bot]``
    convention — this is enforced by the platform, not a heuristic.
    """
    for review in pr.get_reviews():
        if review.state == "APPROVED" and not review.user.login.endswith("[bot]"):
            return True
    return False


_MERGE_METHOD_PREFERENCE = ("SQUASH", "MERGE", "REBASE")


def _allowed_merge_method(pr: PullRequest) -> str:
    """Return a merge method the target repo allows, preferring squash.

    Hardcoding SQUASH fails on repos that disable squash merges (e.g.
    merge-commit-only repos like mozilla/fxa), so fall back to whatever
    the repo actually permits.
    """
    repo = pr.base.repo
    allowed = {
        "SQUASH": repo.allow_squash_merge,
        "MERGE": repo.allow_merge_commit,
        "REBASE": repo.allow_rebase_merge,
    }
    for method in _MERGE_METHOD_PREFERENCE:
        if allowed.get(method):
            return method
    return "MERGE"


def enable_auto_merge(pr: PullRequest) -> str | None:
    """Enable auto-merge on a PR via the GraphQL API.

    Returns None on success, or an error message string on failure.

    The REST API merge endpoint requires elevated permissions that
    GITHUB_TOKEN in Actions doesn't have with branch protection.
    The GraphQL enablePullRequestAutoMerge mutation works with the
    standard token and lets GitHub merge once protection rules pass.

    Uses a merge method the repo allows (see _allowed_merge_method);
    hardcoding SQUASH fails on repos that only allow merge commits.
    """
    method = _allowed_merge_method(pr)
    query = """
    mutation EnableAutoMerge($prId: ID!, $method: PullRequestMergeMethod!) {
      enablePullRequestAutoMerge(
        input: {pullRequestId: $prId, mergeMethod: $method}
      ) {
        pullRequest { autoMergeRequest { enabledAt } }
      }
    }
    """
    _, data = pr._requester.requestJsonAndCheck(
        "POST",
        "/graphql",
        input={
            "query": query,
            "variables": {"prId": pr.node_id, "method": method},
        },
    )
    errors = data.get("errors")
    if errors:
        return "; ".join(e.get("message", str(e)) for e in errors)
    return None


def blender_approved_head(pr: PullRequest) -> bool:
    """True if BLEnder already has an APPROVED review on the current head SHA.

    Used to avoid re-submitting an identical approval every sweep when a
    later step (enabling auto-merge) keeps failing — otherwise a PR can
    collect hundreds of duplicate approvals and never converge.
    """
    head = pr.head.sha
    for review in pr.get_reviews():
        if (
            review.state == "APPROVED"
            and review.user.login == BOT_LOGIN
            and review.commit_id == head
        ):
            return True
    return False


def merge_pr(pr: PullRequest) -> str | None:
    """Merge a PR directly via the GraphQL API.

    Returns None on success, or an error message string on failure.

    Used when auto-merge cannot be armed because the PR is already
    mergeable: repos with no required status checks reach a "clean"
    state immediately, so enablePullRequestAutoMerge is refused and the
    PR must be merged directly. Uses a repo-allowed merge method.
    """
    method = _allowed_merge_method(pr)
    query = """
    mutation MergePR($prId: ID!, $method: PullRequestMergeMethod!) {
      mergePullRequest(input: {pullRequestId: $prId, mergeMethod: $method}) {
        pullRequest { merged }
      }
    }
    """
    _, data = pr._requester.requestJsonAndCheck(
        "POST",
        "/graphql",
        input={
            "query": query,
            "variables": {"prId": pr.node_id, "method": method},
        },
    )
    errors = data.get("errors")
    if errors:
        return "; ".join(e.get("message", str(e)) for e in errors)
    return None
