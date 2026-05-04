"""Tests for scripts.post_alert_action."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from scripts.post_alert_action import (
    create_advisory_and_fork,
    find_existing_pr,
    load_verdict,
    open_bump_pr,
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
