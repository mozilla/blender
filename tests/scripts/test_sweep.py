"""Tests for scripts.sweep.process_repo."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

from scripts.sweep import process_repo

# --- Shared timestamps ---

T_EARLY = datetime(2025, 1, 1, tzinfo=timezone.utc)
T_LATE = datetime(2025, 1, 2, tzinfo=timezone.utc)


# --- Mock builders ---


def _make_commit(message: str, date: datetime = T_EARLY):
    """Build a mock commit object."""
    c = MagicMock()
    c.commit.message = message
    c.commit.committer.date = date
    return c


def _make_comment(login: str, body: str, created_at: datetime = T_EARLY):
    """Build a mock issue comment."""
    c = MagicMock()
    c.user.login = login
    c.body = body
    c.created_at = created_at
    return c


def _make_pr(
    number: int,
    ci_status: str,
    comments: list | None = None,
    commits: list | None = None,
    blender_commit: bool = False,
    is_dependabot: bool = True,
):
    """Build a mock PR with configurable CI, comments, and commits.

    ci_status: "passing" | "failing" | "pending"
    """
    pr = MagicMock()
    pr.number = number
    pr.title = "Bump foo from 1.0.0 to 2.0.0"
    pr.user.login = "dependabot[bot]" if is_dependabot else "octocat"
    type(pr.head).sha = PropertyMock(return_value="abc123")

    commit_list = list(commits or [])
    if blender_commit:
        commit_list.append(_make_commit("BLEnder fix(foo): update lockfile", T_LATE))
    if not commit_list:
        commit_list.append(_make_commit("Bump foo from 1.0.0 to 2.0.0"))
    pr.get_commits.return_value = commit_list
    pr.get_issue_comments.return_value = list(comments or [])

    return pr, ci_status


def _run_sweep(prs: list[tuple[MagicMock, str]]) -> list:
    """Build a mock repo, patch check_pr_status, and run process_repo."""
    repo = MagicMock()
    repo.full_name = "owner/repo"
    repo.get_contents.return_value = True
    repo.get_pulls.return_value = [pr for pr, _ in prs]

    status_map = {pr.number: status for pr, status in prs}

    def mock_check_pr_status(_repo, pr):
        s = status_map[pr.number]
        if s == "passing":
            return "automerge"
        elif s == "failing":
            return "fix"
        return None

    with patch("scripts.sweep.check_pr_status", side_effect=mock_check_pr_status):
        return process_repo(repo)


# --- CI-failing PRs (result == "fix") ---


class TestFixDispatch:
    def test_fresh_pr_dispatches_fix(self):
        """No BLEnder activity -> dispatch fix."""
        actions = _run_sweep([_make_pr(1, "failing")])
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_blender_commit_skips(self):
        """BLEnder commit exists -> skip."""
        actions = _run_sweep([_make_pr(2, "failing", blender_commit=True)])
        assert actions == []

    def test_fresh_picked_up_comment_skips(self):
        """Fresh 'picked up' comment -> skip."""
        pr, status = _make_pr(
            3,
            "failing",
            commits=[_make_commit("Bump foo", T_EARLY)],
            comments=[
                _make_comment("blender[bot]", "BLEnder picked up this PR.", T_LATE)
            ],
        )
        assert _run_sweep([(pr, status)]) == []

    def test_stale_picked_up_comment_dispatches(self):
        """Stale 'picked up' comment (before force-push) -> dispatch fix."""
        pr, status = _make_pr(
            4,
            "failing",
            commits=[_make_commit("Bump foo", T_LATE)],
            comments=[
                _make_comment("blender[bot]", "BLEnder picked up this PR.", T_EARLY)
            ],
        )
        actions = _run_sweep([(pr, status)])
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_fresh_could_not_fix_skips(self):
        """Fresh 'could not fix' comment -> skip."""
        pr, status = _make_pr(
            5,
            "failing",
            commits=[_make_commit("Bump foo", T_EARLY)],
            comments=[
                _make_comment(
                    "blender[bot]",
                    "BLEnder could not fix this PR automatically.",
                    T_LATE,
                )
            ],
        )
        assert _run_sweep([(pr, status)]) == []

    def test_stale_could_not_fix_dispatches(self):
        """Stale 'could not fix' comment -> dispatch fix."""
        pr, status = _make_pr(
            6,
            "failing",
            commits=[_make_commit("Bump foo", T_LATE)],
            comments=[
                _make_comment(
                    "blender[bot]",
                    "BLEnder could not fix this PR automatically.",
                    T_EARLY,
                )
            ],
        )
        actions = _run_sweep([(pr, status)])
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_automerge_comment_does_not_block_fix(self):
        """'will not auto-merge' comment only -> dispatch fix."""
        pr, status = _make_pr(
            7,
            "failing",
            comments=[
                _make_comment(
                    "blender[bot]",
                    "BLEnder: will not auto-merge (CI has 1 failure(s)).",
                    T_LATE,
                )
            ],
        )
        actions = _run_sweep([(pr, status)])
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_retry_comment_does_not_block_fix(self):
        """'skipped (...). Will retry' comment only -> dispatch fix."""
        pr, status = _make_pr(
            8,
            "failing",
            comments=[
                _make_comment(
                    "blender[bot]",
                    "BLEnder: skipped (score unknown). Will retry on next scheduled run.",
                    T_LATE,
                )
            ],
        )
        actions = _run_sweep([(pr, status)])
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_blender_commit_takes_precedence_over_stale_comment(self):
        """BLEnder commit + stale comment -> skip (commit wins)."""
        pr, status = _make_pr(
            9,
            "failing",
            blender_commit=True,
            commits=[_make_commit("Bump foo", T_LATE)],
            comments=[
                _make_comment("blender[bot]", "BLEnder picked up this PR.", T_EARLY)
            ],
        )
        assert _run_sweep([(pr, status)]) == []


# --- CI-passing PRs (result == "automerge") ---


class TestAutomergeDispatch:
    def test_passing_pr_dispatches_automerge(self):
        """No activity -> dispatch automerge."""
        actions = _run_sweep([_make_pr(10, "passing")])
        assert len(actions) == 1
        assert actions[0].action == "automerge"

    def test_blender_comments_do_not_block_automerge(self):
        """BLEnder comments don't block automerge dispatch."""
        pr, status = _make_pr(
            11,
            "passing",
            comments=[
                _make_comment("blender[bot]", "BLEnder picked up this PR.", T_LATE)
            ],
        )
        actions = _run_sweep([(pr, status)])
        assert len(actions) == 1
        assert actions[0].action == "automerge"


# --- CI-pending PRs ---


class TestPendingPR:
    def test_pending_pr_skipped(self):
        """Pending checks -> skip."""
        assert _run_sweep([_make_pr(12, "pending")]) == []


# --- Edge cases ---


class TestEdgeCases:
    def test_non_dependabot_pr_skipped(self):
        """Non-dependabot PR -> not in the list at all."""
        assert _run_sweep([_make_pr(13, "failing", is_dependabot=False)]) == []

    def test_no_blender_config_skips(self):
        """No .blender config -> skip repo."""
        from github.GithubException import UnknownObjectException

        repo = MagicMock()
        repo.get_contents.side_effect = UnknownObjectException(404, {}, {})
        assert process_repo(repo) == []

    def test_check_pr_status_exception_continues(self):
        """Exception in check_pr_status -> skip PR, don't crash."""
        pr, _ = _make_pr(15, "failing")
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo.get_contents.return_value = True
        repo.get_pulls.return_value = [pr]

        with patch(
            "scripts.sweep.check_pr_status", side_effect=RuntimeError("API error")
        ):
            assert process_repo(repo) == []
