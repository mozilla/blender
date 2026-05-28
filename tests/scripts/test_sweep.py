"""Tests for scripts.sweep.process_repo and check_alerts."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from tests.scripts import make_branch, make_comment, make_commit, make_review, make_tag

from scripts.sweep import (
    ALLOWED_OWNERS,
    check_alerts,
    fetch_investigated_alerts,
    process_repo,
    sweep,
)

# --- Shared timestamps ---

T_EARLY = datetime(2025, 1, 1, tzinfo=timezone.utc)
T_LATE = datetime(2025, 1, 2, tzinfo=timezone.utc)


def _make_pr(
    number: int,
    ci_status: str,
    comments: list | None = None,
    commits: list | None = None,
    blender_commit: bool = False,
    is_dependabot: bool = True,
    reviews: list | None = None,
):
    """Build a mock PR with configurable CI, comments, and commits.

    ci_status: "passing" | "failing" | "pending"
    """
    pr = MagicMock()
    pr.number = number
    pr.title = "Bump foo from 1.0.0 to 2.0.0"
    pr.user.login = "dependabot[bot]" if is_dependabot else "octocat"
    pr.head.ref = "dependabot/npm_and_yarn/foo-2.0.0"
    type(pr.head).sha = PropertyMock(return_value="abc123")

    commit_list = list(commits or [])
    if blender_commit:
        commit_list.append(make_commit("BLEnder fix(foo): update lockfile", T_LATE))
    if not commit_list:
        commit_list.append(make_commit("Bump foo from 1.0.0 to 2.0.0"))
    pr.get_commits.return_value = commit_list
    pr.get_issue_comments.return_value = list(comments or [])
    pr.get_reviews.return_value = list(reviews or [])

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
            commits=[make_commit("Bump foo", T_EARLY)],
            comments=[
                make_comment("BLEnder picked up this PR.", "blender[bot]", T_LATE)
            ],
        )
        assert _run_sweep([(pr, status)]) == []

    def test_stale_picked_up_comment_dispatches(self):
        """Stale 'picked up' comment (before force-push) -> dispatch fix."""
        pr, status = _make_pr(
            4,
            "failing",
            commits=[make_commit("Bump foo", T_LATE)],
            comments=[
                make_comment("BLEnder picked up this PR.", "blender[bot]", T_EARLY)
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
            commits=[make_commit("Bump foo", T_EARLY)],
            comments=[
                make_comment(
                    "BLEnder could not fix this PR automatically.",
                    "blender[bot]",
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
            commits=[make_commit("Bump foo", T_LATE)],
            comments=[
                make_comment(
                    "BLEnder could not fix this PR automatically.",
                    "blender[bot]",
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
                make_comment(
                    "BLEnder: will not auto-merge (CI has 1 failure(s)).",
                    "blender[bot]",
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
                make_comment(
                    "BLEnder: skipped (score unknown). Will retry on next scheduled run.",
                    "blender[bot]",
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
            commits=[make_commit("Bump foo", T_LATE)],
            comments=[
                make_comment("BLEnder picked up this PR.", "blender[bot]", T_EARLY)
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
                make_comment("BLEnder picked up this PR.", "blender[bot]", T_LATE)
            ],
        )
        actions = _run_sweep([(pr, status)])
        assert len(actions) == 1
        assert actions[0].action == "automerge"


# --- BLEnder bump PRs ---


def _make_blender_bump_pr(number: int, ci_status: str, package: str = "foo"):
    """Build a mock BLEnder bump PR."""
    pr = MagicMock()
    pr.number = number
    pr.title = f"chore(deps): bump {package} to 2.0.0"
    pr.user.login = "mozilla-blender[bot]"
    pr.head.ref = f"blender/security-bump-{package}"
    type(pr.head).sha = PropertyMock(return_value="abc123")
    pr.get_commits.return_value = [make_commit(f"chore(deps): bump {package}")]
    pr.get_issue_comments.return_value = []
    return pr, ci_status


class TestBlenderBumpPR:
    def test_passing_blender_bump_dispatches_automerge(self):
        """Passing BLEnder bump PR -> automerge."""
        actions = _run_sweep([_make_blender_bump_pr(20, "passing")])
        assert len(actions) == 1
        assert actions[0].action == "automerge"

    def test_failing_blender_bump_dispatches_fix(self):
        """Failing BLEnder bump PR -> dispatch fix."""
        actions = _run_sweep([_make_blender_bump_pr(21, "failing")])
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_pending_blender_bump_skips(self):
        """Pending BLEnder bump PR -> skip."""
        actions = _run_sweep([_make_blender_bump_pr(22, "pending")])
        assert actions == []

    def test_wrong_author_not_picked_up(self):
        """PR on blender/security-bump- branch but wrong author -> ignored."""
        pr, status = _make_blender_bump_pr(23, "passing")
        pr.user.login = "evil-user"
        actions = _run_sweep([(pr, status)])
        assert actions == []

    def test_wrong_branch_not_picked_up(self):
        """PR from BLEnder bot but wrong branch prefix -> ignored."""
        pr, status = _make_blender_bump_pr(24, "passing")
        pr.head.ref = "sneaky/security-bump-foo"
        actions = _run_sweep([(pr, status)])
        assert actions == []


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


# --- Alert discovery ---


def _make_alert(number: int, package: str, severity: str = "high"):
    """Build a mock Dependabot alert dict (API response shape)."""
    return {
        "number": number,
        "security_vulnerability": {
            "package": {"name": package, "ecosystem": "npm"},
            "first_patched_version": {"identifier": "2.0.0"},
        },
        "security_advisory": {"severity": severity},
    }


class TestAlertDiscovery:
    def test_alert_discovery_emits_investigate_action(self):
        """Open alert with no existing branch -> investigate action."""
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo._requester.requestJsonAndCheck.return_value = (
            {},
            [_make_alert(42, "lodash")],
        )
        repo.get_branches.return_value = []

        actions = check_alerts(repo)
        assert len(actions) == 1
        assert actions[0].action == "investigate"
        assert actions[0].alert_number == 42
        assert actions[0].alert_package == "lodash"

    def test_alert_with_existing_branch_skipped(self):
        """Alert with blender/security/{number}-* branch -> skip."""
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo._requester.requestJsonAndCheck.return_value = (
            {},
            [_make_alert(42, "lodash")],
        )
        repo.get_branches.return_value = [
            make_branch("blender/security/42-lodash"),
        ]

        actions = check_alerts(repo)
        assert actions == []

    def test_fixed_alert_skipped(self):
        """No open alerts -> empty list."""
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo._requester.requestJsonAndCheck.return_value = ({}, [])
        repo.get_branches.return_value = []

        actions = check_alerts(repo)
        assert actions == []

    def test_alert_api_failure_returns_empty(self):
        """API error fetching alerts -> empty list, no crash."""
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo._requester.requestJsonAndCheck.side_effect = RuntimeError("403")
        repo.get_branches.return_value = []

        actions = check_alerts(repo)
        assert actions == []

    @pytest.mark.parametrize(
        "alert_number, package, expected_count",
        [
            (138, "minimatch", 0),  # matches investigated set -> skip
            (999, "new-vuln", 1),  # not in investigated set -> emit
        ],
        ids=["investigated-skipped", "uninvestigated-emitted"],
    )
    def test_investigated_alert_dedup(self, alert_number, package, expected_count):
        """Alerts in the investigated set are skipped; others are emitted."""
        repo = MagicMock()
        repo.full_name = "mozilla/blurts-server"
        repo._requester.requestJsonAndCheck.return_value = (
            {},
            [_make_alert(alert_number, package)],
        )
        repo.get_branches.return_value = []

        investigated = {("mozilla/blurts-server", 138)}
        actions = check_alerts(repo, investigated=investigated)
        assert len(actions) == expected_count


# --- fetch_investigated_alerts ---


class TestFetchInvestigatedAlerts:
    def test_parses_investigated_tags(self):
        """Investigated tags are parsed into (repo, alert_number) pairs."""
        tags = [
            make_tag("investigated/mozilla/blurts-server/138"),
            make_tag("investigated/mozilla/fx-private-relay/161"),
            make_tag("v1.0.0"),  # unrelated tag, ignored
        ]

        integration = MagicMock()
        install = MagicMock()
        integration.get_repo_installation.return_value = install
        gh = MagicMock()
        integration.get_github_for_installation.return_value = gh
        gh.get_repo.return_value.get_tags.return_value = tags

        result = fetch_investigated_alerts(integration)
        assert ("mozilla/blurts-server", 138) in result
        assert ("mozilla/fx-private-relay", 161) in result
        assert len(result) == 2

    def test_api_failure_returns_empty_set(self):
        """API error -> empty set, no crash."""
        integration = MagicMock()
        integration.get_repo_installation.side_effect = RuntimeError("oops")

        result = fetch_investigated_alerts(integration)
        assert result == set()


# --- Code-owner approval resets fix guards ---


class TestCodeownerApprovalResetsFix:
    def test_codeowner_approval_overrides_blender_commit(self):
        """Code owner approved + BLEnder commit -> dispatch fix anyway."""
        pr, status = _make_pr(
            30,
            "failing",
            blender_commit=True,
            reviews=[make_review("some-codeowner")],
        )
        actions = _run_sweep([(pr, status)])
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_codeowner_approval_overrides_fresh_fix_comment(self):
        """Code owner approved + fresh 'could not fix' comment -> dispatch fix."""
        pr, status = _make_pr(
            31,
            "failing",
            commits=[make_commit("Bump foo", T_EARLY)],
            comments=[
                make_comment(
                    "BLEnder could not fix this PR automatically.",
                    "blender[bot]",
                    T_LATE,
                )
            ],
            reviews=[make_review("some-codeowner")],
        )
        actions = _run_sweep([(pr, status)])
        assert len(actions) == 1
        assert actions[0].action == "fix"

    def test_bot_approval_does_not_override(self):
        """Bot approval + BLEnder commit -> still skip."""
        pr, status = _make_pr(
            32,
            "failing",
            blender_commit=True,
            reviews=[make_review("some-app[bot]")],
        )
        actions = _run_sweep([(pr, status)])
        assert actions == []


# --- Owner allowlist ---


class TestOwnerAllowlist:
    def test_allowed_owner_is_processed(self):
        """Repo under an allowed owner -> process it."""
        assert "mozilla" in ALLOWED_OWNERS

    def test_disallowed_owner_is_skipped(self):
        """Repo under an unknown owner -> skipped, no process_repo call."""
        repo = MagicMock()
        repo.full_name = "abenj1062-hash/arnika"

        installation = MagicMock()
        installation.id = 999
        installation.get_repos.return_value = [repo]

        integration = MagicMock()
        integration.get_installations.return_value = [installation]

        with (
            patch("scripts.sweep.GithubIntegration", return_value=integration),
            patch("scripts.sweep.Auth.AppAuth"),
            patch("scripts.sweep.fetch_investigated_alerts", return_value=set()),
            patch("scripts.sweep.process_repo") as mock_process,
        ):
            actions = sweep("12345", "fake-key")

        mock_process.assert_not_called()
        assert actions == []
