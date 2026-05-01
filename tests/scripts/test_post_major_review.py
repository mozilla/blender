"""Tests for scripts.post_major_review."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scripts.github_utils import Verdict
from scripts.post_major_review import main
from tests.scripts.test_automerge_dependabot import _make_mock


@patch("scripts.post_major_review.Github")
def test_no_duplicate_verdict_comment(mock_gh_cls, monkeypatch, tmp_path):
    """post_comment skips if a verdict comment already exists."""
    # main() reads .blender-verdict.json from disk, so the test must create it.
    verdict_file = tmp_path / ".blender-verdict.json"
    verdict_file.write_text(
        json.dumps(
            {
                "safe": False,
                "confidence": "low",
                "reason": "Breaking API change",
                "breaking_changes": ["removed foo()"],
                "affected_code": ["bar.py"],
                "test_coverage": "none",
            }
        )
    )

    monkeypatch.setenv("PR_NUMBER", "10")
    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.chdir(tmp_path)

    pr = MagicMock()
    pr.get_issue_comments.return_value = [
        _make_mock(Verdict.NEEDS_REVIEW.comment())
    ]
    pr.get_reviews.return_value = []
    mock_gh_cls.return_value.get_repo.return_value.get_pull.return_value = pr

    main()

    pr.create_issue_comment.assert_not_called()


@patch("scripts.post_major_review.Github")
@patch("scripts.post_major_review.enable_auto_merge")
def test_safe_verdict_approves_and_merges(mock_merge, mock_gh_cls, monkeypatch, tmp_path):
    """Safe + high confidence verdict approves and enables auto-merge."""
    # main() reads .blender-verdict.json from disk, so the test must create it.
    verdict_file = tmp_path / ".blender-verdict.json"
    verdict_file.write_text(
        json.dumps(
            {
                "safe": True,
                "confidence": "high",
                "reason": "No breaking changes affect this codebase",
                "breaking_changes": [],
                "affected_code": [],
                "test_coverage": "good",
            }
        )
    )

    monkeypatch.setenv("PR_NUMBER", "10")
    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.chdir(tmp_path)

    pr = MagicMock()
    pr.get_issue_comments.return_value = []
    pr.get_reviews.return_value = []
    mock_gh_cls.return_value.get_repo.return_value.get_pull.return_value = pr

    main()

    pr.create_review.assert_called_once()
    mock_merge.assert_called_once_with(pr)
    pr.create_issue_comment.assert_called_once()
    comment_text = pr.create_issue_comment.call_args.args[0]
    assert comment_text.startswith("SAFE:")
