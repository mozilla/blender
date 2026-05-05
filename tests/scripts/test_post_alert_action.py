"""Tests for scripts.post_alert_action."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from scripts.post_alert_action import (
    create_advisory_and_fork,
    dismiss_alert,
    find_existing_pr,
    load_verdict,
    main,
    open_bump_pr,
    post_summary_comment,
)


@pytest.fixture()
def verdict_file(tmp_path, monkeypatch):
    """Write a verdict JSON and chdir so load_verdict finds it."""
    monkeypatch.chdir(tmp_path)

    def _write(data: dict):
        (tmp_path / ".blender-alert-verdict.json").write_text(json.dumps(data))

    return _write


class TestLoadVerdict:
    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert load_verdict() is None

    def test_valid_verdict(self, verdict_file):
        verdict_file({
            "affected": False,
            "confidence": "high",
            "reason": "not used",
            "vulnerable_paths": [],
            "recommended_action": "bump_pr",
        })
        v = load_verdict()
        assert v is not None
        assert v["affected"] is False

    def test_missing_keys(self, verdict_file):
        verdict_file({"affected": True})
        assert load_verdict() is None


class TestFindExistingPR:
    def test_finds_matching_pr(self):
        pr = MagicMock()
        pr.user.login = "dependabot[bot]"
        pr.title = "Bump lodash from 4.17.20 to 4.17.21"
        pr.number = 99
        repo = MagicMock()
        repo.get_pulls.return_value = [pr]

        assert find_existing_pr(repo, "lodash") is True

    def test_no_matching_pr(self):
        pr = MagicMock()
        pr.user.login = "dependabot[bot]"
        pr.title = "Bump express from 4.0 to 5.0"
        repo = MagicMock()
        repo.get_pulls.return_value = [pr]

        assert find_existing_pr(repo, "lodash") is False


class TestOpenBumpPR:
    def test_dry_run_skips_creation(self):
        repo = MagicMock()
        open_bump_pr(repo, 42, "lodash", "4.17.21", "npm", dry_run=True)
        repo.create_git_ref.assert_not_called()
        repo.create_pull.assert_not_called()

    def test_existing_branch_skips(self):
        repo = MagicMock()
        repo.get_branch.return_value = MagicMock()  # branch exists
        open_bump_pr(repo, 42, "lodash", "4.17.21", "npm", dry_run=False)
        repo.create_git_ref.assert_not_called()


class TestCreateAdvisoryAndFork:
    def test_dry_run_skips(self):
        repo = MagicMock()
        ghsa, fork = create_advisory_and_fork(repo, 42, "lodash", dry_run=True)
        assert ghsa == ""
        assert fork == ""
        repo._requester.requestJsonAndCheck.assert_not_called()

    def test_duplicate_advisory_skipped(self):
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo._requester.requestJsonAndCheck.side_effect = Exception(
            "422 already exists"
        )
        ghsa, fork = create_advisory_and_fork(repo, 42, "lodash", dry_run=False)
        assert ghsa == ""
        assert fork == ""


class TestDismissAlert:
    def test_calls_api(self):
        repo = MagicMock()
        repo.full_name = "owner/repo"
        dismiss_alert(repo, 42, "not used in codebase", dry_run=False)
        repo._requester.requestJsonAndCheck.assert_called_once_with(
            "PATCH",
            "/repos/owner/repo/dependabot/alerts/42",
            input={
                "state": "dismissed",
                "dismissed_reason": "inaccurate",
                "dismissed_comment": "BLEnder: not used in codebase",
            },
        )

    def test_dry_run_skips(self):
        repo = MagicMock()
        dismiss_alert(repo, 42, "not used", dry_run=True)
        repo._requester.requestJsonAndCheck.assert_not_called()


class TestPostSummaryComment:
    def test_creates_issue_when_missing(self):
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo.get_issues.return_value = iter([])
        new_issue = MagicMock()
        new_issue.number = 10
        repo.create_issue.return_value = new_issue

        post_summary_comment(repo, 42, "lodash", "high", "dismissed", "not used", False)

        repo.create_issue.assert_called_once()
        new_issue.create_comment.assert_called_once()
        comment = new_issue.create_comment.call_args[0][0]
        assert "#42" in comment
        assert "lodash" in comment

    def test_reuses_existing_issue(self):
        repo = MagicMock()
        repo.full_name = "owner/repo"
        existing = MagicMock()
        existing.title = "BLEnder: Dependabot alert investigation summary"
        repo.get_issues.return_value = iter([existing])

        post_summary_comment(repo, 7, "express", "medium", "bump_pr", "outdated", False)

        repo.create_issue.assert_not_called()
        existing.create_comment.assert_called_once()

    def test_dry_run_skips(self):
        repo = MagicMock()
        post_summary_comment(repo, 42, "lodash", "high", "dismissed", "not used", True)
        repo.get_issues.assert_not_called()


class TestMainDismissFlow:
    def test_not_affected_dismiss_enabled(self, verdict_file, monkeypatch):
        verdict_file({
            "affected": False,
            "confidence": "high",
            "reason": "not used in codebase",
            "vulnerable_paths": [],
            "recommended_action": "bump_pr",
        })
        monkeypatch.setenv("GH_TOKEN", "fake")
        monkeypatch.setenv("REPO", "owner/repo")
        monkeypatch.setenv("ALERT_NUMBER", "42")
        monkeypatch.setenv("ALERT_PACKAGE", "lodash")
        monkeypatch.setenv("ALERT_ECOSYSTEM", "npm")
        monkeypatch.setenv("ALERT_SEVERITY", "high")
        monkeypatch.setenv("DISMISS_NOT_AFFECTED", "true")
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_issues.return_value = iter([])
        mock_issue = MagicMock()
        mock_issue.number = 1
        mock_repo.create_issue.return_value = mock_issue

        with patch("scripts.post_alert_action.Github") as mock_gh:
            mock_gh.return_value.get_repo.return_value = mock_repo
            main()

        # Alert was dismissed
        mock_repo._requester.requestJsonAndCheck.assert_called_once_with(
            "PATCH",
            "/repos/owner/repo/dependabot/alerts/42",
            input={
                "state": "dismissed",
                "dismissed_reason": "inaccurate",
                "dismissed_comment": "BLEnder: not used in codebase",
            },
        )
        # Summary comment was posted
        mock_issue.create_comment.assert_called_once()
