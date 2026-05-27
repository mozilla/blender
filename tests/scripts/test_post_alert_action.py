"""Tests for scripts.post_alert_action."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from scripts.alert_report import (
    annotation_line,
    render_markdown,
    write_step_summary,
)
from scripts.post_alert_action import (
    create_advisory_and_fork,
    create_bump_pr,
    dismiss_alert,
    find_dependency_pin,
    find_existing_bump_pr,
    load_verdict,
    main,
    request_dependabot_update,
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
                "dismissed_reason": "not_used",
                "dismissed_comment": "BLEnder: not used in codebase",
            },
        )

    def test_dry_run_skips(self):
        repo = MagicMock()
        dismiss_alert(repo, 42, "not used", dry_run=True)
        repo._requester.requestJsonAndCheck.assert_not_called()


class TestRenderMarkdown:
    def test_contains_key_elements(self):
        result = render_markdown(
            "owner/repo", 42, "lodash", "high", "dismissed", SAMPLE_VERDICT
        )
        assert "Alert #42" in result
        assert "lodash" in result
        assert "NOT AFFECTED" in result
        assert "not used in codebase" in result
        assert "dismissed" in result.lower()

    def test_affected_redacts_details(self):
        verdict = {
            "affected": True,
            "confidence": "high",
            "reason": "lodash.merge called with user input",
            "vulnerable_paths": ["server.js:2"],
            "recommended_action": "private_fork",
        }
        result = render_markdown(
            "owner/repo", 42, "lodash", "high", "private_fork", verdict
        )
        assert "AFFECTED" in result
        assert "lodash.merge called" not in result
        assert "security advisory" in result.lower()


class TestAnnotationLine:
    def test_unaffected_dismissed(self):
        result = annotation_line(42, "lodash", "dismissed", SAMPLE_VERDICT)
        assert "not affected" in result
        assert "alert dismissed" in result
        assert "high confidence" in result

    def test_affected_fork(self):
        verdict = {**SAMPLE_VERDICT, "affected": True}
        result = annotation_line(42, "lodash", "private_fork", verdict)
        assert "affected" in result
        assert "private fork" in result


class TestWriteStepSummary:
    def test_writes_to_github_step_summary(self, tmp_path, monkeypatch):
        summary_file = str(tmp_path / "summary.md")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", summary_file)
        write_step_summary(
            "owner/repo", 42, "lodash", "high", "dismissed", SAMPLE_VERDICT
        )
        content = open(summary_file).read()
        assert "Alert #42" in content
        assert "lodash" in content

    def test_skips_without_env_var(self, monkeypatch):
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        # Should not raise
        write_step_summary(
            "owner/repo", 42, "lodash", "high", "dismissed", SAMPLE_VERDICT
        )


class TestMainFlow:
    """Integration tests for main() with various verdict + config combos."""

    def _run_main(self, verdict_file, tmp_path, monkeypatch, mock_repo, **env_overrides):
        """Helper to set up env vars and run main()."""
        summary_file = str(tmp_path / "step-summary.md")
        defaults = {
            "GH_TOKEN": "fake",
            "REPO": "owner/repo",
            "ALERT_NUMBER": "42",
            "ALERT_PACKAGE": "lodash",
            "ALERT_ECOSYSTEM": "npm",
            "ALERT_SEVERITY": "low",
            "DISMISS_UNAFFECTED": "false",
            "DRY_RUN": "false",
            "GITHUB_STEP_SUMMARY": summary_file,
        }
        defaults.update(env_overrides)
        for k, v in defaults.items():
            monkeypatch.setenv(k, v)
        if "GITHUB_OUTPUT" not in env_overrides:
            monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        with patch("scripts.post_alert_action.Github") as mock_gh:
            mock_gh.return_value.get_repo.return_value = mock_repo
            main()

        return summary_file

    def test_bump_pr_creates_pr(
        self, verdict_file, tmp_path, monkeypatch
    ):
        verdict_file(SAMPLE_VERDICT)
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.default_branch = "main"
        mock_repo.get_pulls.return_value = []  # no existing PR

        # Mock finding the dependency pin
        mock_file = MagicMock()
        mock_file.decoded_content = b"lodash==4.17.20\nrequests==2.28.0\n"
        mock_file.sha = "abc123"
        mock_repo.get_contents.return_value = mock_file

        # Mock branch creation
        mock_ref = MagicMock()
        mock_ref.object.sha = "def456"
        mock_repo.get_git_ref.side_effect = [
            mock_ref,  # get default branch ref
            Exception("not found"),  # branch doesn't exist yet
        ]

        # Mock PR creation
        mock_pr = MagicMock()
        mock_pr.number = 101
        mock_pr.html_url = "https://github.com/owner/repo/pull/101"
        mock_repo.create_pull.return_value = mock_pr

        summary_file = self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            ALERT_ECOSYSTEM="pip", ALERT_PATCHED_VERSION="4.17.21",
        )

        mock_repo.create_pull.assert_called_once()
        content = open(summary_file).read()
        assert "Bump PR created" in content

    def test_existing_pr_gets_comment(
        self, verdict_file, tmp_path, monkeypatch
    ):
        verdict_file(SAMPLE_VERDICT)
        mock_pr = MagicMock()
        mock_pr.number = 99
        mock_pr.title = "Bump lodash from 4.17.20 to 4.17.21"
        mock_pr.user.login = "dependabot[bot]"
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = [mock_pr]

        summary_file = self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo
        )

        mock_repo.get_pull.assert_called_once_with(99)
        mock_repo.get_pull.return_value.create_issue_comment.assert_called_once()
        content = open(summary_file).read()
        assert "Existing" in content

    def test_existing_pr_dry_run_skips_comment(
        self, verdict_file, tmp_path, monkeypatch
    ):
        verdict_file(SAMPLE_VERDICT)
        mock_pr = MagicMock()
        mock_pr.number = 99
        mock_pr.title = "Bump lodash from 4.17.20 to 4.17.21"
        mock_pr.user.login = "dependabot[bot]"
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = [mock_pr]

        self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo, DRY_RUN="true"
        )

        mock_repo.get_pull.assert_not_called()

    def test_dismiss_enabled_low_severity_with_existing_pr(
        self, verdict_file, tmp_path, monkeypatch
    ):
        """With existing PR, we comment on it instead of dismissing."""
        verdict = {**SAMPLE_VERDICT, "recommended_action": "existing_pr"}
        verdict_file(verdict)
        mock_pr = MagicMock()
        mock_pr.number = 99
        mock_pr.title = "Bump lodash from 4.17.20 to 4.17.21"
        mock_pr.user.login = "dependabot[bot]"
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = [mock_pr]

        self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            DISMISS_UNAFFECTED="true", ALERT_SEVERITY="low",
        )

        # Should comment on PR, not dismiss
        mock_repo.get_pull.assert_called_once_with(99)

    def test_dismiss_enabled_no_pr_no_bump(
        self, verdict_file, tmp_path, monkeypatch
    ):
        """With dismiss enabled and recommended_action != bump_pr, dismiss."""
        verdict = {**SAMPLE_VERDICT, "recommended_action": "none"}
        verdict_file(verdict)
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []

        self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            DISMISS_UNAFFECTED="true", ALERT_SEVERITY="low",
        )

        mock_repo._requester.requestJsonAndCheck.assert_called_once_with(
            "PATCH",
            "/repos/owner/repo/dependabot/alerts/42",
            input={
                "state": "dismissed",
                "dismissed_reason": "not_used",
                "dismissed_comment": "BLEnder: not used in codebase",
            },
        )

    def test_dismiss_skips_high_severity(
        self, verdict_file, tmp_path, monkeypatch
    ):
        verdict = {**SAMPLE_VERDICT, "recommended_action": "none"}
        verdict_file(verdict)
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []

        self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            DISMISS_UNAFFECTED="true", ALERT_SEVERITY="high",
        )

        mock_repo._requester.requestJsonAndCheck.assert_not_called()

    def test_npm_bump_outputs_action(
        self, verdict_file, tmp_path, monkeypatch
    ):
        """npm ecosystem with bump_pr verdict emits action=npm_bump.

        The npm path never calls create_bump_pr — main() handles it
        directly by writing outputs for the workflow's npm_bump step.
        """
        verdict_file(SAMPLE_VERDICT)
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []  # no existing PR

        output_file = str(tmp_path / "github_output")
        open(output_file, "w").close()

        self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            ALERT_ECOSYSTEM="npm", ALERT_PATCHED_VERSION="1.0.1",
            GITHUB_OUTPUT=output_file,
        )

        outputs = open(output_file).read()
        assert "action=npm_bump" in outputs
        assert "npm_package=lodash" in outputs
        assert "npm_version=1.0.1" in outputs

        # npm path should not touch repo contents or create PRs
        mock_repo.get_contents.assert_not_called()
        mock_repo.create_pull.assert_not_called()

    def test_npm_bump_no_patched_version(
        self, verdict_file, tmp_path, monkeypatch
    ):
        """npm ecosystem without patched version results in noop."""
        verdict_file(SAMPLE_VERDICT)
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []

        output_file = str(tmp_path / "github_output")
        open(output_file, "w").close()

        self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            ALERT_ECOSYSTEM="npm", ALERT_PATCHED_VERSION="",
            GITHUB_OUTPUT=output_file,
        )

        outputs = open(output_file).read()
        assert "action=noop" in outputs


class TestRequestDependabotUpdate:
    def test_dry_run_skips(self):
        repo = MagicMock()
        result = request_dependabot_update(repo, 42, "idna", dry_run=True)
        assert result == "dependabot_requested"
        repo._requester.requestJsonAndCheck.assert_not_called()

    def test_enables_automated_fixes(self):
        repo = MagicMock()
        repo.full_name = "owner/repo"
        result = request_dependabot_update(repo, 42, "idna", dry_run=False)
        assert result == "dependabot_requested"
        repo._requester.requestJsonAndCheck.assert_called_once_with(
            "PUT", "/repos/owner/repo/automated-security-fixes"
        )

    def test_already_enabled_succeeds(self):
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo._requester.requestJsonAndCheck.side_effect = Exception("409 Conflict")
        result = request_dependabot_update(repo, 42, "idna", dry_run=False)
        assert result == "dependabot_requested"

    def test_api_failure_returns_none(self):
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo._requester.requestJsonAndCheck.side_effect = Exception("500 Server Error")
        result = request_dependabot_update(repo, 42, "idna", dry_run=False)
        assert result is None


class TestFallbackToDependabot:
    """Integration: pip transitive dep with no pin falls back to Dependabot."""

    def test_pip_no_pin_requests_dependabot(
        self, verdict_file, tmp_path, monkeypatch
    ):
        verdict_file(SAMPLE_VERDICT)
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []
        # get_contents raises for every file — no pin found
        mock_repo.get_contents.side_effect = Exception("404 Not Found")

        output_file = str(tmp_path / "github_output")
        open(output_file, "w").close()

        summary_file = str(tmp_path / "step-summary.md")
        for k, v in {
            "GH_TOKEN": "fake",
            "REPO": "owner/repo",
            "ALERT_NUMBER": "2",
            "ALERT_PACKAGE": "idna",
            "ALERT_ECOSYSTEM": "pip",
            "ALERT_SEVERITY": "high",
            "ALERT_PATCHED_VERSION": "3.15",
            "DRY_RUN": "false",
            "DISMISS_UNAFFECTED": "false",
            "GITHUB_STEP_SUMMARY": summary_file,
            "GITHUB_OUTPUT": output_file,
        }.items():
            monkeypatch.setenv(k, v)

        with patch("scripts.post_alert_action.Github") as mock_gh:
            mock_gh.return_value.get_repo.return_value = mock_repo
            main()

        outputs = open(output_file).read()
        assert "action=dependabot_requested" in outputs
        content = open(summary_file).read()
        assert "Dependabot security update requested" in content
