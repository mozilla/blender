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
    detect_js_package_manager,
    detect_pip_lock_tool,
    dismiss_alert,
    fetch_patched_version,
    find_dependency_pin,
    find_existing_bump_pr,
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


# Dismissal policy cases exercised through main() (see TestMainFlow).
# Each: (id, extra env, verdict overrides, expected step-summary note substring).
NOT_DISMISSED_CASES = [
    ("low_confidence", {"ALERT_SEVERITY": "low"}, {"confidence": "low"}, "below required: high"),
    ("medium_below_default_bar", {"ALERT_SEVERITY": "low"}, {"confidence": "medium"}, "below required: high"),
    ("empty_confidence", {"ALERT_SEVERITY": "low"}, {"confidence": ""}, "confidence: unknown. below required: high"),
    ("invalid_min_confidence", {"ALERT_SEVERITY": "low", "DISMISS_MIN_CONFIDENCE": "hgih"}, {"confidence": "medium"}, None),
    ("high_above_default_ceiling", {"ALERT_SEVERITY": "high"}, {"confidence": "high"}, "above ceiling: medium"),
    ("critical_above_high_ceiling", {"ALERT_SEVERITY": "critical", "DISMISS_MAX_SEVERITY": "high"}, {"confidence": "high"}, "above ceiling: high"),
    ("invalid_max_severity", {"ALERT_SEVERITY": "high", "DISMISS_MAX_SEVERITY": "huge"}, {"confidence": "high"}, None),
    ("unknown_severity", {"ALERT_SEVERITY": ""}, {"confidence": "high"}, "needs manual review"),
    ("unrecognized_severity", {"ALERT_SEVERITY": "moderate", "DISMISS_MAX_SEVERITY": "critical"}, {"confidence": "high"}, "needs manual review"),
]

DISMISSED_CASES = [
    ("low_default_bar", {"ALERT_SEVERITY": "low"}, {"confidence": "high"}),
    ("medium_bar_lowered", {"ALERT_SEVERITY": "low", "DISMISS_MIN_CONFIDENCE": "medium"}, {"confidence": "medium"}),
    ("high_ceiling_raised", {"ALERT_SEVERITY": "high", "DISMISS_MAX_SEVERITY": "high"}, {"confidence": "high"}),
    ("critical_ceiling", {"ALERT_SEVERITY": "critical", "DISMISS_MAX_SEVERITY": "critical"}, {"confidence": "high"}),
]


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

    def test_truncates_long_comment(self):
        """GitHub caps dismissed_comment at 280 chars; a long reason must not 422."""
        repo = MagicMock()
        repo.full_name = "owner/repo"
        dismiss_alert(repo, 42, "x" * 500, dry_run=False)
        args, kwargs = repo._requester.requestJsonAndCheck.call_args
        comment = kwargs["input"]["dismissed_comment"]
        assert len(comment) <= 280
        assert comment.endswith("...")


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

    def test_note_renders_when_present(self):
        result = render_markdown(
            "owner/repo", 42, "lodash", "low", "noop", SAMPLE_VERDICT,
            note="not dismissed. confidence: low. below required: high",
        )
        assert "**Note**" in result
        assert "below required: high" in result

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
            "ALERT_PATCHED_VERSION": "1.0.0",
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

    @pytest.mark.parametrize(
        "env, verdict_over, note_substr",
        [c[1:] for c in NOT_DISMISSED_CASES],
        ids=[c[0] for c in NOT_DISMISSED_CASES],
    )
    def test_unaffected_not_dismissed(
        self, verdict_file, tmp_path, monkeypatch, env, verdict_over, note_substr
    ):
        """Not-affected alerts blocked by the confidence floor or severity ceiling
        are left open, with the reason recorded in the step summary."""
        verdict = {**SAMPLE_VERDICT, "recommended_action": "none", **verdict_over}
        verdict_file(verdict)
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []

        summary_file = self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            DISMISS_UNAFFECTED="true", **env,
        )

        mock_repo._requester.requestJsonAndCheck.assert_not_called()
        if note_substr:
            assert note_substr in open(summary_file).read()

    @pytest.mark.parametrize(
        "env, verdict_over",
        [c[1:] for c in DISMISSED_CASES],
        ids=[c[0] for c in DISMISSED_CASES],
    )
    def test_unaffected_dismissed_within_policy(
        self, verdict_file, tmp_path, monkeypatch, env, verdict_over
    ):
        """Not-affected alerts within the severity ceiling and confidence floor
        are dismissed."""
        verdict = {**SAMPLE_VERDICT, "recommended_action": "none", **verdict_over}
        verdict_file(verdict)
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []

        self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            DISMISS_UNAFFECTED="true", **env,
        )

        args = mock_repo._requester.requestJsonAndCheck.call_args
        assert args.args[0] == "PATCH"
        assert args.kwargs["input"]["state"] == "dismissed"

    def test_confidence_note_preserved_on_bump_fallback(
        self, verdict_file, tmp_path, monkeypatch
    ):
        """A below-bar alert that recommends bump_pr still records the confidence note."""
        verdict = {**SAMPLE_VERDICT, "recommended_action": "bump_pr", "confidence": "low"}
        verdict_file(verdict)
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []

        output_file = str(tmp_path / "github_output")
        open(output_file, "w").close()

        summary_file = self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            DISMISS_UNAFFECTED="true", ALERT_SEVERITY="low",
            ALERT_ECOSYSTEM="npm", ALERT_PATCHED_VERSION="1.0.1",
            GITHUB_OUTPUT=output_file,
        )

        # Bumped (not dismissed) because confidence was below the bar...
        assert "action=npm_bump" in open(output_file).read()
        # ...and the summary still explains why it wasn't dismissed (#143).
        assert "below required: high" in open(summary_file).read()

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

        # npm defers to the workflow step; no PR is created here.
        mock_repo.create_pull.assert_not_called()

    def test_yarn_bump_outputs_action(
        self, verdict_file, tmp_path, monkeypatch
    ):
        """A yarn repo (yarn.lock, no package-lock.json) routes to yarn_bump."""
        verdict_file(SAMPLE_VERDICT)
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []  # no existing PR

        def get_contents(path):
            if path == "yarn.lock":
                return MagicMock()
            raise Exception("404")

        mock_repo.get_contents.side_effect = get_contents

        output_file = str(tmp_path / "github_output")
        open(output_file, "w").close()

        self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            ALERT_ECOSYSTEM="npm", ALERT_PATCHED_VERSION="1.0.1",
            GITHUB_OUTPUT=output_file,
        )

        outputs = open(output_file).read()
        assert "action=yarn_bump" in outputs
        assert "yarn_package=lodash" in outputs
        assert "yarn_version=1.0.1" in outputs

    def test_affected_empty_fork_is_advisory_only(
        self, verdict_file, tmp_path, monkeypatch
    ):
        """Affected alert with no private fork -> advisory_only, not private_fork
        (avoids the empty-clone failure that stalled remediation)."""
        verdict_file({**SAMPLE_VERDICT, "affected": True, "recommended_action": "private_fork"})
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        output_file = str(tmp_path / "github_output")
        open(output_file, "w").close()

        with patch(
            "scripts.post_alert_action.create_advisory_and_fork",
            return_value=("GHSA-x", ""),
        ):
            self._run_main(
                verdict_file, tmp_path, monkeypatch, mock_repo,
                GITHUB_OUTPUT=output_file,
            )

        outputs = open(output_file).read()
        assert "action=advisory_only" in outputs
        assert "advisory_ghsa_id=GHSA-x" in outputs
        assert "fork_repo=" not in outputs

    def test_affected_with_fork_is_private_fork(
        self, verdict_file, tmp_path, monkeypatch
    ):
        """Affected alert with a fork still routes to private_fork."""
        verdict_file({**SAMPLE_VERDICT, "affected": True, "recommended_action": "private_fork"})
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        output_file = str(tmp_path / "github_output")
        open(output_file, "w").close()

        with patch(
            "scripts.post_alert_action.create_advisory_and_fork",
            return_value=("GHSA-x", "owner/fork-abc"),
        ):
            self._run_main(
                verdict_file, tmp_path, monkeypatch, mock_repo,
                GITHUB_OUTPUT=output_file,
            )

        outputs = open(output_file).read()
        assert "action=private_fork" in outputs
        assert "fork_repo=owner/fork-abc" in outputs

    def test_dismiss_precedes_npm_bump_for_unaffected(
        self, verdict_file, tmp_path, monkeypatch
    ):
        """Unaffected low/medium alert is dismissed, not routed to npm_bump (#112)."""
        verdict_file(SAMPLE_VERDICT)  # affected=False, recommended_action=bump_pr
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []  # no existing PR

        output_file = str(tmp_path / "github_output")
        open(output_file, "w").close()

        self._run_main(
            verdict_file, tmp_path, monkeypatch, mock_repo,
            ALERT_ECOSYSTEM="npm", ALERT_SEVERITY="medium",
            DISMISS_UNAFFECTED="true", DRY_RUN="true",
            GITHUB_OUTPUT=output_file,
        )

        outputs = open(output_file).read()
        assert "action=dismissed" in outputs
        assert "action=npm_bump" not in outputs

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


class TestFetchPatchedVersion:
    def test_fetches_from_api(self):
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo._requester.requestJsonAndCheck.return_value = (
            None,
            {
                "security_vulnerability": {
                    "first_patched_version": {"identifier": "3.15"},
                }
            },
        )
        assert fetch_patched_version(repo, 2) == "3.15"

    def test_returns_empty_on_api_error(self):
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo._requester.requestJsonAndCheck.side_effect = Exception("403")
        assert fetch_patched_version(repo, 2) == ""

    def test_returns_empty_when_no_patched_version(self):
        repo = MagicMock()
        repo.full_name = "owner/repo"
        repo._requester.requestJsonAndCheck.return_value = (
            None,
            {"security_vulnerability": {}},
        )
        assert fetch_patched_version(repo, 2) == ""


class TestDetectPipLockTool:
    """detect_pip_lock_tool checks files in order: uv.lock, poetry.lock, Pipfile.lock."""

    @pytest.mark.parametrize(
        "files_present, expected_tool",
        [
            ({"uv.lock"}, "uv"),
            ({"poetry.lock"}, "poetry"),
            ({"Pipfile.lock"}, "pipenv"),
            ({"uv.lock", "poetry.lock"}, "uv"),  # uv wins when both exist
            (set(), None),
        ],
        ids=["uv", "poetry", "pipenv", "uv-wins-over-poetry", "none"],
    )
    def test_lock_tool_detection(self, files_present, expected_tool):
        repo = MagicMock()

        def get_contents(path):
            if path in files_present:
                return MagicMock()
            raise Exception("404")

        repo.get_contents.side_effect = get_contents

        result = detect_pip_lock_tool(repo)
        if expected_tool is None:
            assert result is None
        else:
            assert result is not None
            assert result[0] == expected_tool


class TestDetectJsPackageManager:
    """detect_js_package_manager checks lockfiles: package-lock.json, yarn.lock, pnpm-lock.yaml."""

    @pytest.mark.parametrize(
        "files_present, expected",
        [
            ({"package-lock.json"}, "npm"),
            ({"yarn.lock"}, "yarn"),
            ({"pnpm-lock.yaml"}, "pnpm"),
            ({"package-lock.json", "yarn.lock"}, "npm"),  # npm wins when both exist
            (set(), None),
        ],
        ids=["npm", "yarn", "pnpm", "npm-wins", "none"],
    )
    def test_detection(self, files_present, expected):
        repo = MagicMock()

        def get_contents(path):
            if path in files_present:
                return MagicMock()
            raise Exception("404")

        repo.get_contents.side_effect = get_contents

        assert detect_js_package_manager(repo) == expected


class TestPipLockBumpFlow:
    """Integration: pip transitive dep with no pin triggers lock bump."""

    def _run_pip_main(self, verdict_file, tmp_path, monkeypatch, mock_repo):
        """Run main() with pip ecosystem defaults. Returns (outputs, summary)."""
        verdict_file(SAMPLE_VERDICT)

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

        return open(output_file).read(), open(summary_file).read()

    def test_pip_no_pin_with_uv_lock(
        self, verdict_file, tmp_path, monkeypatch
    ):
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []

        def get_contents_side_effect(path):
            if path == "uv.lock":
                return MagicMock()
            raise Exception("404 Not Found")

        mock_repo.get_contents.side_effect = get_contents_side_effect

        outputs, summary = self._run_pip_main(
            verdict_file, tmp_path, monkeypatch, mock_repo
        )
        assert "action=pip_lock_bump" in outputs
        assert "pip_package=idna" in outputs
        assert "pip_version=3.15" in outputs
        assert "pip_lock_tool=uv" in outputs
        assert "pip lock bump" in summary.lower()

    def test_pip_no_pin_no_lock_noop(
        self, verdict_file, tmp_path, monkeypatch
    ):
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.get_pulls.return_value = []
        mock_repo.get_contents.side_effect = Exception("404 Not Found")

        outputs, _ = self._run_pip_main(
            verdict_file, tmp_path, monkeypatch, mock_repo
        )
        assert "action=noop" in outputs
