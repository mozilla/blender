"""Tests for scripts.sweep.process_repo."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from scripts.sweep import process_repo


def _make_commit(message: str, date: datetime | None = None):
    """Build a mock commit object."""
    c = MagicMock()
    c.commit.message = message
    c.commit.committer.date = date or datetime(2025, 1, 1, tzinfo=timezone.utc)
    return c


def _make_comment(login: str, body: str, created_at: datetime | None = None):
    """Build a mock issue comment."""
    c = MagicMock()
    c.user.login = login
    c.body = body
    c.created_at = created_at or datetime(2025, 1, 1, tzinfo=timezone.utc)
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
    pr.title = f"Bump foo from 1.0.0 to 2.0.0"
    pr.user.login = "dependabot[bot]" if is_dependabot else "octocat"
    type(pr.head).sha = PropertyMock(return_value="abc123")

    # Commits
    commit_list = list(commits or [])
    if blender_commit:
        commit_list.append(
            _make_commit(
                "BLEnder fix(foo): update lockfile",
                datetime(2025, 1, 2, tzinfo=timezone.utc),
            )
        )
    if not commit_list:
        commit_list.append(_make_commit("Bump foo from 1.0.0 to 2.0.0"))
    pr.get_commits.return_value = commit_list

    # Comments
    pr.get_issue_comments.return_value = list(comments or [])

    return pr, ci_status


def _build_repo(prs: list[tuple[MagicMock, str]]):
    """Build a mock repo with .blender config and given PRs."""
    repo = MagicMock()
    repo.full_name = "owner/repo"
    # has_blender_config returns True
    repo.get_contents.return_value = True

    pr_objects = [pr for pr, _ in prs]
    repo.get_pulls.return_value = pr_objects

    # Patch check_pr_status to return the configured status
    status_map = {pr.number: status for pr, status in prs}

    def mock_check_pr_status(_repo, pr):
        s = status_map[pr.number]
        if s == "passing":
            return "automerge"
        elif s == "failing":
            return "fix"
        else:
            return None

    return repo, mock_check_pr_status


# --- CI-failing PRs (result == "fix") ---


class TestFixDispatch:
    def test_fresh_pr_dispatches_fix(self):
        """#1: No BLEnder activity -> dispatch fix."""
        pr, status = _make_pr(1, "failing")
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_blender_commit_skips(self):
        """#2: BLEnder commit exists -> skip."""
        pr, status = _make_pr(2, "failing", blender_commit=True)
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert actions == []

    def test_fresh_picked_up_comment_skips(self):
        """#3: Fresh 'picked up' comment -> skip."""
        commit_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        comment_date = datetime(2025, 1, 2, tzinfo=timezone.utc)
        pr, status = _make_pr(
            3,
            "failing",
            commits=[_make_commit("Bump foo", commit_date)],
            comments=[
                _make_comment("blender[bot]", "BLEnder picked up this PR.", comment_date)
            ],
        )
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert actions == []

    def test_stale_picked_up_comment_dispatches(self):
        """#4: Stale 'picked up' comment (before force-push) -> dispatch fix."""
        comment_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        commit_date = datetime(2025, 1, 2, tzinfo=timezone.utc)
        pr, status = _make_pr(
            4,
            "failing",
            commits=[_make_commit("Bump foo", commit_date)],
            comments=[
                _make_comment("blender[bot]", "BLEnder picked up this PR.", comment_date)
            ],
        )
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_fresh_could_not_fix_skips(self):
        """#5: Fresh 'could not fix' comment -> skip."""
        commit_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        comment_date = datetime(2025, 1, 2, tzinfo=timezone.utc)
        pr, status = _make_pr(
            5,
            "failing",
            commits=[_make_commit("Bump foo", commit_date)],
            comments=[
                _make_comment(
                    "blender[bot]",
                    "BLEnder could not fix this PR automatically.",
                    comment_date,
                )
            ],
        )
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert actions == []

    def test_stale_could_not_fix_dispatches(self):
        """#6: Stale 'could not fix' comment -> dispatch fix."""
        comment_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        commit_date = datetime(2025, 1, 2, tzinfo=timezone.utc)
        pr, status = _make_pr(
            6,
            "failing",
            commits=[_make_commit("Bump foo", commit_date)],
            comments=[
                _make_comment(
                    "blender[bot]",
                    "BLEnder could not fix this PR automatically.",
                    comment_date,
                )
            ],
        )
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_automerge_comment_does_not_block_fix(self):
        """#7: 'will not auto-merge' comment only -> dispatch fix."""
        pr, status = _make_pr(
            7,
            "failing",
            comments=[
                _make_comment(
                    "blender[bot]",
                    "BLEnder: will not auto-merge (CI has 1 failure(s)).",
                    datetime(2025, 1, 2, tzinfo=timezone.utc),
                )
            ],
        )
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_retry_comment_does_not_block_fix(self):
        """#8: 'skipped (...). Will retry' comment only -> dispatch fix."""
        pr, status = _make_pr(
            8,
            "failing",
            comments=[
                _make_comment(
                    "blender[bot]",
                    "BLEnder: skipped (score unknown). Will retry on next scheduled run.",
                    datetime(2025, 1, 2, tzinfo=timezone.utc),
                )
            ],
        )
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_blender_commit_takes_precedence_over_stale_comment(self):
        """#9: BLEnder commit + stale comment -> skip (commit wins)."""
        comment_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        commit_date = datetime(2025, 1, 2, tzinfo=timezone.utc)
        pr, status = _make_pr(
            9,
            "failing",
            blender_commit=True,
            commits=[_make_commit("Bump foo", commit_date)],
            comments=[
                _make_comment("blender[bot]", "BLEnder picked up this PR.", comment_date)
            ],
        )
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert actions == []


# --- CI-passing PRs (result == "automerge") ---


class TestAutomergeDispatch:
    def test_passing_pr_dispatches_automerge(self):
        """#10: No activity -> dispatch automerge."""
        pr, status = _make_pr(10, "passing")
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert len(actions) == 1
        assert actions[0].action == "automerge"

    def test_blender_comments_do_not_block_automerge(self):
        """#11: BLEnder comments don't block automerge dispatch."""
        pr, status = _make_pr(
            11,
            "passing",
            comments=[
                _make_comment(
                    "blender[bot]",
                    "BLEnder picked up this PR.",
                    datetime(2025, 1, 2, tzinfo=timezone.utc),
                )
            ],
        )
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert len(actions) == 1
        assert actions[0].action == "automerge"


# --- CI-pending PRs ---


class TestPendingPR:
    def test_pending_pr_skipped(self):
        """#12: Pending checks -> skip."""
        pr, status = _make_pr(12, "pending")
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert actions == []


# --- Edge cases ---


class TestEdgeCases:
    def test_non_dependabot_pr_skipped(self):
        """#13: Non-dependabot PR -> not in the list at all."""
        pr, status = _make_pr(13, "failing", is_dependabot=False)
        repo, checker = _build_repo([(pr, status)])
        with patch("scripts.sweep.check_pr_status", side_effect=checker):
            actions = process_repo(repo)
        assert actions == []

    def test_no_blender_config_skips(self):
        """#14: No .blender config -> skip repo."""
        from github.GithubException import UnknownObjectException

        repo = MagicMock()
        repo.get_contents.side_effect = UnknownObjectException(404, {}, {})
        actions = process_repo(repo)
        assert actions == []

    def test_check_pr_status_exception_continues(self):
        """#15: Exception in check_pr_status -> skip PR, don't crash."""
        pr, _ = _make_pr(15, "failing")
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo.get_contents.return_value = True
        repo.get_pulls.return_value = [pr]

        with patch(
            "scripts.sweep.check_pr_status", side_effect=RuntimeError("API error")
        ):
            actions = process_repo(repo)
        assert actions == []
