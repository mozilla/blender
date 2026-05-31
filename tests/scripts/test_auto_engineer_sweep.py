"""Tests for scripts.sweep.check_auto_engineer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, PropertyMock

import pytest

from tests.scripts import make_branch, make_comment, make_commit, make_issue, make_review

from scripts.sweep import check_auto_engineer

# --- Shared timestamps ---

NOW = datetime.now(timezone.utc)
T_EARLY = NOW - timedelta(hours=2)
T_LATE = NOW - timedelta(minutes=30)

ENABLED_CONFIG = {"auto_engineer": {"enabled": True, "issue_label": "auto-engineer"}}


def _make_ae_pr(
    number: int,
    issue_number: int = 42,
    plan_only: bool = True,
    approved: bool = False,
    comments_after_commit: bool = False,
):
    """Build a mock auto-engineer PR."""
    pr = MagicMock()
    pr.number = number
    pr.title = f"BLEnder: fix issue #{issue_number}"
    pr.merged = False
    pr.merged_at = None
    slug = "fix-the-thing"
    pr.head.ref = f"blender/auto-engineer/{issue_number}-{slug}"

    label = MagicMock()
    label.name = "blender:auto-engineer"
    pr.labels = [label]

    initial_plan_commit = make_commit(f"BLEnder plan(#{issue_number}): initial plan", T_EARLY)
    pr_commits = [initial_plan_commit]
    if not plan_only:
        pr_commits += [make_commit("feat: implement the thing", T_LATE)]
    pr.get_commits.return_value = pr_commits

    reviews = []
    if approved:
        reviews.append(make_review("codeowner", "APPROVED"))
    pr.get_reviews.return_value = reviews

    comments = []
    if comments_after_commit:
        comments.append(
            make_comment("Please change X", login="reviewer", created_at=T_LATE)
        )
    pr.get_issue_comments.return_value = comments

    return pr


def _make_repo(
    open_prs=None,
    closed_prs=None,
    branches=None,
    labeled_issues=None,
    all_issues=None,
):
    """Build a mock repo for auto-engineer tests.

    labeled_issues: returned when get_issues is called with labels kwarg
    all_issues: returned when get_issues is called without labels kwarg
    """
    repo = MagicMock()
    repo.full_name = "mozilla/test-repo"

    repo.get_pulls.side_effect = lambda state="open", **kw: (
        list(open_prs or []) if state == "open" else list(closed_prs or [])
    )
    repo.get_branches.return_value = list(branches or [])

    def get_issues_side_effect(state="open", **kwargs):
        if "labels" in kwargs:
            return list(labeled_issues or [])
        if all_issues is not None:
            return list(all_issues)
        return list(labeled_issues or [])

    repo.get_issues = MagicMock(side_effect=get_issues_side_effect)

    return repo


class TestFeatureDisabled:
    def test_disabled_config_no_action(self):
        """auto_engineer.enabled=false → no action."""
        repo = _make_repo()
        assert check_auto_engineer(repo, {}) == []
        assert check_auto_engineer(repo, {"auto_engineer": {"enabled": False}}) == []


class TestNoIssues:
    def test_no_open_issues_no_action(self):
        """No open issues at all → no action."""
        repo = _make_repo(labeled_issues=[], all_issues=[])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert actions == []


class TestLabeledIssue:
    def test_labeled_issue_emits_plan(self):
        """Labeled issue exists, no PR → emits plan action."""
        issue = make_issue(42, "Fix the widget", labels=["auto-engineer"])
        repo = _make_repo(labeled_issues=[issue])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert len(actions) == 1
        assert actions[0].action == "auto-engineer"
        assert actions[0].phase == "plan"
        assert actions[0].issue_number == 42

    def test_issue_with_existing_branch_skipped(self):
        """Issue already has a branch → skip new plan.

        Follow-up work (implement, feedback) routes through the open PR
        check above, not the issue/branch check.
        """
        issue = make_issue(42, "Fix the widget", labels=["auto-engineer"])
        branch = make_branch("blender/auto-engineer/42-fix-the-widget")
        repo = _make_repo(labeled_issues=[issue], branches=[branch], all_issues=[])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert actions == []

    def test_assigned_issue_skipped(self):
        """Assigned issue → skip."""
        assignee = MagicMock()
        issue = make_issue(
            42, "Fix the widget", labels=["auto-engineer"], assignees=[assignee]
        )
        repo = _make_repo(labeled_issues=[issue], all_issues=[])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert actions == []


class TestBugLabelPriority:
    def test_bug_label_picked_first(self):
        """Bug-labeled issue picked over non-bug issue."""
        normal = make_issue(10, "Add feature", labels=["auto-engineer"])
        bug = make_issue(20, "Fix crash", labels=["auto-engineer", "bug"])
        repo = _make_repo(labeled_issues=[normal, bug])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert len(actions) == 1
        assert actions[0].issue_number == 20

    def test_no_bug_picks_newest(self):
        """No bug label → picks first (newest) issue."""
        old = make_issue(10, "Old issue", labels=["auto-engineer"])
        new = make_issue(20, "New issue", labels=["auto-engineer"])
        repo = _make_repo(labeled_issues=[new, old])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert len(actions) == 1
        assert actions[0].issue_number == 20


class TestTrustedAuthorFiltering:
    def test_untrusted_author_skipped(self):
        """Issue from untrusted author (NONE) → skipped."""
        issue = make_issue(
            42, "Inject me", labels=["auto-engineer"], author_association="NONE"
        )
        repo = _make_repo(labeled_issues=[issue], all_issues=[])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert actions == []

    def test_custom_trusted_associations(self):
        """Custom trusted_author_associations includes MEMBER."""
        issue = make_issue(
            42, "Member issue", labels=["auto-engineer"], author_association="MEMBER"
        )
        config = {
            "auto_engineer": {
                "enabled": True,
                "issue_label": "auto-engineer",
                "trusted_author_associations": "OWNER,MEMBER",
            }
        }
        repo = _make_repo(labeled_issues=[issue])
        actions = check_auto_engineer(repo, config)
        assert len(actions) == 1
        assert actions[0].issue_number == 42


class TestNoLabeledIssues:
    def test_fallback_emits_plan_with_zero(self):
        """No labeled issues but trusted open issues exist → plan with issue_number=0."""
        issue = make_issue(10, "Some random issue", author_association="OWNER")
        repo = _make_repo(labeled_issues=[], all_issues=[issue])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert len(actions) == 1
        assert actions[0].issue_number == 0

    def test_fallback_skips_untrusted_issues(self):
        """Fallback path filters out untrusted authors."""
        issue = make_issue(10, "Untrusted issue", author_association="NONE")
        repo = _make_repo(labeled_issues=[], all_issues=[issue])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert actions == []


class TestPlanPR:
    def test_plan_pr_no_comments_no_action(self):
        """Plan PR exists, no comments → waiting for review."""
        pr = _make_ae_pr(100, plan_only=True)
        repo = _make_repo(open_prs=[pr])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert actions == []

    def test_plan_pr_with_comments_emits_plan(self):
        """Plan PR with comments after commit → address feedback."""
        pr = _make_ae_pr(100, plan_only=True, comments_after_commit=True)
        repo = _make_repo(open_prs=[pr])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert len(actions) == 1
        assert actions[0].phase == "plan"
        assert actions[0].pr_number == 100

    def test_plan_pr_approved_emits_implement(self):
        """Plan PR approved → implement."""
        pr = _make_ae_pr(100, plan_only=True, approved=True)
        repo = _make_repo(open_prs=[pr])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert len(actions) == 1
        assert actions[0].phase == "implement"
        assert actions[0].pr_number == 100


class TestImplementationPR:
    def test_impl_pr_no_comments_no_action(self):
        """Implementation PR, no comments → waiting for review."""
        pr = _make_ae_pr(100, plan_only=False)
        repo = _make_repo(open_prs=[pr])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert actions == []

    def test_impl_pr_with_comments_emits_implement(self):
        """Implementation PR with comments → address feedback."""
        pr = _make_ae_pr(100, plan_only=False, comments_after_commit=True)
        repo = _make_repo(open_prs=[pr])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert len(actions) == 1
        assert actions[0].phase == "implement"
        assert actions[0].pr_number == 100


class TestSelfReview:
    def test_merged_pr_no_self_review_emits_action(self):
        """Merged PR, no self-review comment → emits self-review."""
        pr = _make_ae_pr(100, plan_only=False)
        pr.merged = True
        pr.merged_at = NOW - timedelta(hours=1)
        pr.get_issue_comments.return_value = []
        repo = _make_repo(closed_prs=[pr])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert len(actions) == 1
        assert actions[0].phase == "self-review"
        assert actions[0].pr_number == 100

    def test_merged_pr_with_self_review_no_action(self):
        """Merged PR, self-review already posted → no action."""
        pr = _make_ae_pr(100, plan_only=False)
        pr.merged = True
        pr.merged_at = NOW - timedelta(hours=1)
        pr.get_issue_comments.return_value = [
            make_comment(
                "## Self-Review\n\nAll good.",
                login="mozilla-blender[bot]",
                created_at=T_LATE,
            )
        ]
        repo = _make_repo(closed_prs=[pr])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert actions == []

    def test_old_merged_pr_ignored(self):
        """Merged PR older than 24 hours → no action."""
        pr = _make_ae_pr(100, plan_only=False)
        pr.merged = True
        pr.merged_at = NOW - timedelta(hours=25)
        pr.get_issue_comments.return_value = []
        repo = _make_repo(closed_prs=[pr])
        actions = check_auto_engineer(repo, ENABLED_CONFIG)
        assert actions == []


class TestConfigForwarding:
    def test_config_fields_on_action(self):
        """Action.to_dict() includes config fields when set."""
        from scripts.sweep import Action

        a = Action(
            action="auto-engineer",
            repo="mozilla/test",
            pr_number=0,
            pr_title="",
            phase="plan",
            issue_number=42,
            issue_title="test",
            trusted_author_associations="OWNER,MEMBER",
            forbidden_paths=".env",
        )
        d = a.to_dict()
        assert d["trusted_author_associations"] == "OWNER,MEMBER"
        assert d["forbidden_paths"] == ".env"

    def test_config_fields_omitted_when_none(self):
        """Action.to_dict() omits config fields when None."""
        from scripts.sweep import Action

        a = Action(
            action="auto-engineer",
            repo="mozilla/test",
            pr_number=0,
            pr_title="",
            phase="plan",
            issue_number=42,
            issue_title="test",
        )
        d = a.to_dict()
        assert "trusted_author_associations" not in d
        assert "forbidden_paths" not in d
