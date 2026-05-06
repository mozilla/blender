"""Tests for scripts.post_alert_action."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from scripts.post_alert_action import (
    create_advisory_and_fork,
    dismiss_alert,
    load_verdict,
    main,
    write_summary,
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


class TestWriteSummary:
    def test_writes_json(self, tmp_path):
        path = str(tmp_path / "summary.json")
        write_summary(path, 42, "lodash", "high", "dismissed", "not used")
        data = json.loads(open(path).read())
        assert data == {
            "alert_number": 42,
            "package": "lodash",
            "severity": "high",
            "action": "dismissed",
            "reason": "not used",
        }


class TestMainDismissFlow:
    def test_unaffected_dismiss_enabled(self, verdict_file, tmp_path, monkeypatch):
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
        monkeypatch.setenv("DISMISS_UNAFFECTED", "true")
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"

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
        # Summary was written to file
        summary_path = str(tmp_path / ".blender-alert-summary.json")
        assert os.path.exists(summary_path)
        data = json.loads(open(summary_path).read())
        assert data["action"] == "dismissed"
        assert data["alert_number"] == 42

    def test_unaffected_dismiss_disabled_is_noop(
        self, verdict_file, tmp_path, monkeypatch
    ):
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
        monkeypatch.setenv("DISMISS_UNAFFECTED", "false")
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"

        with patch("scripts.post_alert_action.Github") as mock_gh:
            mock_gh.return_value.get_repo.return_value = mock_repo
            main()

        # No API mutations
        mock_repo._requester.requestJsonAndCheck.assert_not_called()
        # Summary still written
        summary_path = str(tmp_path / ".blender-alert-summary.json")
        assert os.path.exists(summary_path)
        data = json.loads(open(summary_path).read())
        assert data["action"] == "noop"
