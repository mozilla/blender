"""Tests for scripts.post_alert_action."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from scripts.alert_report import read_code_snippet, render_html, write_summary
from scripts.post_alert_action import (
    create_advisory_and_fork,
    dismiss_alert,
    load_verdict,
    main,
)


@pytest.fixture()
def verdict_file(tmp_path, monkeypatch):
    """Write a verdict JSON and chdir so load_verdict finds it."""
    monkeypatch.chdir(tmp_path)

    def _write(data: dict):
        (tmp_path / ".blender-alert-verdict.json").write_text(json.dumps(data))

    return _write


SAMPLE_VERDICT = {
    "affected": False,
    "confidence": "high",
    "reason": "not used in codebase",
    "vulnerable_paths": [],
    "recommended_action": "bump_pr",
}


class TestLoadVerdict:
    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert load_verdict() is None

    def test_valid_verdict(self, verdict_file):
        verdict_file(SAMPLE_VERDICT)
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


class TestReadCodeSnippet:
    def test_reads_lines_around_target(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text("\n".join(f"line {i}" for i in range(1, 21)))
        lines = read_code_snippet(str(src), 10)
        nums = [n for n, _, _ in lines]
        assert 10 in nums
        # Target line is marked
        targets = [(n, hit) for n, _, hit in lines if hit]
        assert targets == [(10, True)]

    def test_missing_file_returns_empty(self):
        assert read_code_snippet("/no/such/file.py", 5) == []

    def test_target_near_start(self, tmp_path):
        src = tmp_path / "short.py"
        src.write_text("a\nb\nc\n")
        lines = read_code_snippet(str(src), 1)
        assert lines[0][0] == 1
        assert lines[0][2] is True


class TestRenderHtml:
    def test_contains_key_elements(self):
        verdict = {**SAMPLE_VERDICT, "vulnerable_paths": []}
        result = render_html("owner/repo", 42, "lodash", "high", "dismissed", verdict)
        assert "Alert #42" in result
        assert "lodash" in result
        assert "UNAFFECTED" in result
        assert "not used in codebase" in result

    def test_affected_redacts_details(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "server.js"
        src.write_text("const x = require('lodash');\nx.merge({}, input);\n")
        verdict = {
            "affected": True,
            "confidence": "high",
            "reason": "lodash.merge called with user input",
            "vulnerable_paths": ["server.js:2"],
            "recommended_action": "private_fork",
        }
        result = render_html(
            "owner/repo", 42, "lodash", "high", "private_fork", verdict
        )
        assert "AFFECTED" in result
        # Sensitive details must not appear in the public artifact
        assert "lodash.merge called" not in result
        assert "server.js:2" not in result
        assert "x.merge" not in result
        assert "see the security advisory" in result.lower()

    def test_unaffected_shows_code_snippets(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "util.js"
        src.write_text("function safe() {}\nmodule.exports = safe;\n")
        verdict = {
            **SAMPLE_VERDICT,
            "vulnerable_paths": ["util.js:1"],
        }
        result = render_html(
            "owner/repo", 42, "lodash", "high", "dismissed", verdict
        )
        assert "util.js:1" in result
        assert "function safe" in result

    def test_missing_source_file(self):
        verdict = {
            **SAMPLE_VERDICT,
            "vulnerable_paths": ["/nonexistent/file.py:10"],
        }
        result = render_html(
            "owner/repo", 42, "lodash", "high", "dismissed", verdict
        )
        assert "Source file not available" in result

    def test_path_without_line_number(self):
        verdict = {
            **SAMPLE_VERDICT,
            "vulnerable_paths": ["some/file.py"],
        }
        result = render_html(
            "owner/repo", 42, "lodash", "high", "dismissed", verdict
        )
        assert "No line number specified" in result


class TestWriteSummary:
    def test_writes_html(self, tmp_path):
        path = str(tmp_path / "summary.html")
        write_summary(
            path, "owner/repo", 42, "lodash", "high", "dismissed", SAMPLE_VERDICT
        )
        content = open(path).read()
        assert content.startswith("<!DOCTYPE html>")
        assert "Alert #42" in content
        assert "lodash" in content


class TestMainDismissFlow:
    def test_unaffected_dismiss_enabled(self, verdict_file, tmp_path, monkeypatch):
        verdict_file(SAMPLE_VERDICT)
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

        mock_repo._requester.requestJsonAndCheck.assert_called_once_with(
            "PATCH",
            "/repos/owner/repo/dependabot/alerts/42",
            input={
                "state": "dismissed",
                "dismissed_reason": "inaccurate",
                "dismissed_comment": "BLEnder: not used in codebase",
            },
        )
        summary_path = str(tmp_path / ".blender-alert-summary.html")
        assert os.path.exists(summary_path)
        content = open(summary_path).read()
        assert "dismissed" in content.lower()

    def test_unaffected_dismiss_disabled_is_noop(
        self, verdict_file, tmp_path, monkeypatch
    ):
        verdict_file(SAMPLE_VERDICT)
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

        mock_repo._requester.requestJsonAndCheck.assert_not_called()
        summary_path = str(tmp_path / ".blender-alert-summary.html")
        assert os.path.exists(summary_path)
        content = open(summary_path).read()
        assert "No action taken" in content
