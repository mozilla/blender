"""Tests for scripts.automerge_dependabot."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.automerge_dependabot import (
    AdvisorySkipPR,
    DependencyUpdate,
    MajorBumpPR,
    PRMetadata,
    SkipPR,
    _normalize_pep440_range,
    _post_dependabot_recreate,
    gate_advisories,
    gate_versions,
    version_in_range,
)
from scripts.github_utils import Verdict, has_blender_verdict


# --- _normalize_pep440_range ---


class TestNormalizePep440Range:
    def test_single_equals(self):
        assert _normalize_pep440_range("= 4.5.0") == "== 4.5.0"

    def test_double_equals_unchanged(self):
        assert _normalize_pep440_range("== 4.5.0") == "== 4.5.0"

    def test_gte_unchanged(self):
        assert _normalize_pep440_range(">= 1.0.0") == ">= 1.0.0"

    def test_lte_unchanged(self):
        assert _normalize_pep440_range("<= 2.0.0") == "<= 2.0.0"

    def test_mixed(self):
        assert _normalize_pep440_range(">= 1.0, = 2.0") == ">= 1.0, == 2.0"


# --- version_in_range with npm ecosystem ---

# These are real advisory ranges from Next.js GHSA entries.
NEXTJS_ADVISORY_RANGES = [
    ">= 13.0.0, < 14.2.24",
    ">= 15.0.0-canary.0, < 15.0.0-rc.1",
    ">= 15.0.0, < 15.2.4",
    ">= 14.0.0-canary.0, < 14.0.0-rc.1",
    ">= 14.0.0, < 14.2.24",
    ">= 15.0.0-canary.0, < 15.0.0-rc.1",
    ">= 15.0.0, < 15.2.4",
    ">= 11.1.0, < 14.2.24",
    ">= 15.0.0-canary, < 15.2.4",
]


class TestVersionInRangeNpm:
    @pytest.mark.parametrize("range_str", NEXTJS_ADVISORY_RANGES)
    def test_16_2_4_not_in_advisory_ranges(self, range_str: str):
        """16.2.4 is above every known advisory range."""
        assert version_in_range("16.2.4", range_str, "npm") is False

    def test_true_positive(self):
        """14.2.23 is inside '>= 11.1.0, < 14.2.24'."""
        assert version_in_range("14.2.23", ">= 11.1.0, < 14.2.24", "npm") is True

    def test_fix_boundary(self):
        """14.2.24 is the fix version — not in range."""
        assert version_in_range("14.2.24", ">= 11.1.0, < 14.2.24", "npm") is False

    def test_single_equals(self):
        """'= 1.0.0' means exactly 1.0.0."""
        assert version_in_range("1.0.0", "= 1.0.0", "npm") is True
        assert version_in_range("1.0.1", "= 1.0.0", "npm") is False

    def test_canary_range(self):
        """Canary prereleases inside a canary range are vulnerable."""
        assert (
            version_in_range(
                "15.0.0-canary.50",
                ">= 15.0.0-canary.0, < 15.0.0-rc.1",
                "npm",
            )
            is True
        )

    def test_beta_outside_canary_range(self):
        """A stable release is above a canary-only range's upper bound."""
        assert (
            version_in_range(
                "15.1.0",
                ">= 15.0.0-canary.0, < 15.0.0-rc.1",
                "npm",
            )
            is False
        )


# --- version_in_range with pip ecosystem ---


class TestVersionInRangePip:
    def test_prerelease_excluded_by_default(self):
        """PEP 440: prereleases excluded from non-prerelease ranges."""
        assert version_in_range("2.0.0a1", ">= 1.0, < 2.0", "pip") is False

    def test_explicit_prerelease_range(self):
        """PEP 440: prereleases need explicit opt-in via prereleases=True.

        SpecifierSet doesn't auto-enable prereleases across compound
        specifiers, so 2.0.0a1 is NOT matched by '>= 2.0a0, < 2.0.0'.
        The semver fallback also returns False. This is a known limitation.
        """
        assert version_in_range("2.0.0a1", ">= 2.0a0, < 2.0.0", "pip") is False

    def test_standard_range_in(self):
        assert version_in_range("1.5.0", ">= 1.0, < 2.0", "pip") is True

    def test_standard_range_out(self):
        assert version_in_range("2.0.0", ">= 1.0, < 2.0", "pip") is False

    def test_single_equals(self):
        """'= 3.1.0' (advisory style) matches exactly."""
        assert version_in_range("3.1.0", "= 3.1.0", "pip") is True
        assert version_in_range("3.1.1", "= 3.1.0", "pip") is False


# --- Fallback behavior ---


class TestVersionInRangeFallback:
    def test_unknown_ecosystem_uses_semver(self):
        """Unknown ecosystem falls through to semver."""
        assert version_in_range("1.5.0", ">= 1.0.0, < 2.0.0", "rubygems") is True
        assert version_in_range("2.0.0", ">= 1.0.0, < 2.0.0", "rubygems") is False

    def test_nodesemver_handles_garbage(self):
        """nodesemver returns False for garbage — does not raise.

        The 'assume vulnerable' fallback (return True) is unreachable
        in practice because nodesemver never raises on bad input.
        """
        assert version_in_range("not_a_version", "not_a_range", "") is False
        assert version_in_range("", "", "") is False


# --- gate_advisories raises AdvisorySkipPR ---


def test_gate_advisories_raises_advisory_skip_pr():
    """Advisory on the new version raises AdvisorySkipPR, not bare SkipPR."""
    meta = PRMetadata(
        dependencies=[
            DependencyUpdate(
                name="lodash",
                version="4.17.20",
                dependency_type="direct:production",
                update_type="version-update:semver-patch",
            )
        ],
        ecosystem="npm",
        raw_ecosystem="npm_and_yarn",
    )

    vuln = MagicMock()
    vuln.vulnerable_version_range = ">= 4.0.0, < 4.17.21"
    vuln.package = MagicMock()
    vuln.package.name = "lodash"

    advisory = MagicMock()
    advisory.ghsa_id = "GHSA-abcd-1234-efgh"
    advisory.vulnerabilities = [vuln]

    gh = MagicMock()
    gh.get_global_advisories.return_value = [advisory]

    with pytest.raises(AdvisorySkipPR, match="GHSA-abcd-1234-efgh"):
        gate_advisories(gh, meta)


# --- _post_dependabot_recreate ---


def test_post_dependabot_recreate_comment_text():
    """Exact text matters — Dependabot parses commands literally."""
    pr = MagicMock()
    pr.number = 42
    _post_dependabot_recreate(pr, dry_run=False)
    pr.create_issue_comment.assert_called_once_with("@dependabot recreate")


# --- main loop: advisory skip triggers recreate, regular skip does not ---


@pytest.mark.parametrize(
    "exception, expect_recreate",
    [
        (AdvisorySkipPR("advisory on lodash@4.17.20"), True),
        (SkipPR("major version bump"), False),
    ],
)
@patch("scripts.automerge_dependabot.process_pr")
def test_main_loop_recreate_on_advisory_skip_only(
    mock_process,
    exception,
    expect_recreate,
    monkeypatch,
):
    from scripts.automerge_dependabot import main

    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("DRY_RUN", "false")

    pr = MagicMock()
    pr.number = 7
    pr.user.login = "dependabot[bot]"
    pr.head.ref = "dependabot/npm_and_yarn/lodash-4.17.21"
    pr.get_issue_comments.return_value = []

    mock_process.side_effect = exception

    with patch("scripts.automerge_dependabot.Github") as gh_cls:
        gh_cls.return_value.get_repo.return_value.get_pulls.return_value = [pr]
        main()

    recreate_calls = [
        c
        for c in pr.create_issue_comment.call_args_list
        if c.args[0] == "@dependabot recreate"
    ]
    assert len(recreate_calls) == (1 if expect_recreate else 0)


# --- MajorBumpPR ---


def test_gate_versions_raises_major_bump_pr():
    """gate_versions raises MajorBumpPR (not bare SkipPR) for major bumps."""
    dep = DependencyUpdate(
        name="python-ipware",
        version="7.0.0",
        dependency_type="direct:production",
        update_type="version-update:semver-major",
        old_version="6.0.5",
    )
    meta = PRMetadata(
        dependencies=[dep],
        has_major=True,
        old_version="6.0.5",
        new_version="7.0.0",
    )
    with pytest.raises(MajorBumpPR, match="python-ipware") as exc_info:
        gate_versions(meta, allow_major=False)
    assert exc_info.value.dep is dep
    assert exc_info.value.meta is meta


@patch("scripts.automerge_dependabot.process_pr")
def test_main_outputs_major_bumps_json(mock_process, monkeypatch, tmp_path):
    """MajorBumpPR exceptions are collected and written to GITHUB_OUTPUT."""
    import json
    from scripts.automerge_dependabot import main

    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("REVIEW_MAJOR", "true")

    output_file = tmp_path / "github_output"
    output_file.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    dep = DependencyUpdate(
        name="ipware",
        version="7.0.0",
        dependency_type="direct:production",
        update_type="version-update:semver-major",
        old_version="6.0.5",
    )
    meta = PRMetadata(
        dependencies=[dep],
        has_major=True,
        ecosystem="pip",
        raw_ecosystem="pip",
        old_version="6.0.5",
        new_version="7.0.0",
    )
    mock_process.side_effect = MajorBumpPR(
        "major version bump on ipware",
        dep=dep,
        meta=meta,
    )

    pr = MagicMock()
    pr.number = 42
    pr.title = "Bump ipware from 6.0.5 to 7.0.0"
    pr.user.login = "dependabot[bot]"
    pr.head.ref = "dependabot/pip/ipware-7.0.0"
    pr.get_issue_comments.return_value = []
    pr.get_reviews.return_value = []

    with patch("scripts.automerge_dependabot.Github") as gh_cls:
        gh_cls.return_value.get_repo.return_value.get_pulls.return_value = [pr]
        main()

    output = output_file.read_text()
    assert "major_bumps=" in output
    bumps = json.loads(output.split("major_bumps=", 1)[1].strip())
    assert len(bumps) == 1
    assert bumps[0]["pr_number"] == 42
    assert bumps[0]["dep_name"] == "ipware"


@patch("scripts.automerge_dependabot.process_pr")
def test_main_no_comment_when_review_major(mock_process, monkeypatch):
    """When REVIEW_MAJOR=true, MajorBumpPR posts no comment (workflow handles it)."""
    from scripts.automerge_dependabot import main

    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("REVIEW_MAJOR", "true")

    dep = DependencyUpdate(
        name="ipware",
        version="7.0.0",
        dependency_type="direct:production",
        update_type="version-update:semver-major",
    )
    meta = PRMetadata(dependencies=[dep], has_major=True)
    mock_process.side_effect = MajorBumpPR(
        "major version bump on ipware",
        dep=dep,
        meta=meta,
    )

    pr = MagicMock()
    pr.number = 42
    pr.title = "Bump ipware from 6.0.5 to 7.0.0"
    pr.user.login = "dependabot[bot]"
    pr.head.ref = "dependabot/pip/ipware-7.0.0"
    pr.get_issue_comments.return_value = []
    pr.get_reviews.return_value = []

    with patch("scripts.automerge_dependabot.Github") as gh_cls:
        gh_cls.return_value.get_repo.return_value.get_pulls.return_value = [pr]
        main()

    pr.create_issue_comment.assert_not_called()


# --- has_blender_verdict ---


def _gh_comment(body: str, login: str = "blender[bot]"):
    """Build a mock GitHub comment/review object with .body and .user.login."""
    m = MagicMock()
    m.body = body
    m.user.login = login
    return m


@pytest.mark.parametrize(
    "verdict",
    [Verdict.SAFE, Verdict.NEEDS_REVIEW, Verdict.NO_VERDICT, Verdict.MALFORMED],
)
def test_has_blender_verdict_from_comment(verdict):
    pr = MagicMock()
    pr.get_issue_comments.return_value = [_gh_comment(body=verdict.comment("extra."))]
    pr.get_reviews.return_value = []
    assert has_blender_verdict(pr) is True


def test_has_blender_verdict_from_review():
    pr = MagicMock()
    pr.get_issue_comments.return_value = []
    pr.get_reviews.return_value = [
        _gh_comment(body=Verdict.APPROVED.comment("(high confidence)."))
    ]
    assert has_blender_verdict(pr) is True


def test_has_blender_verdict_false_when_no_verdict():
    pr = MagicMock()
    pr.get_issue_comments.return_value = [
        _gh_comment(body="Reviewing this major version bump.")
    ]
    pr.get_reviews.return_value = []
    assert has_blender_verdict(pr) is False


def test_has_blender_verdict_ignores_human_comments():
    pr = MagicMock()
    pr.get_issue_comments.return_value = [
        _gh_comment(body=Verdict.SAFE.comment("to merge."), login="groovecoder")
    ]
    pr.get_reviews.return_value = []
    assert has_blender_verdict(pr) is False


@patch("scripts.automerge_dependabot.process_pr")
def test_main_skips_dispatch_when_already_reviewed(mock_process, monkeypatch, tmp_path):
    """Already-reviewed major bumps are not dispatched again."""
    from scripts.automerge_dependabot import main

    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("REVIEW_MAJOR", "true")

    output_file = tmp_path / "github_output"
    output_file.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    dep = DependencyUpdate(
        name="ipware",
        version="7.0.0",
        dependency_type="direct:production",
        update_type="version-update:semver-major",
        old_version="6.0.5",
    )
    meta = PRMetadata(
        dependencies=[dep],
        has_major=True,
        ecosystem="pip",
        raw_ecosystem="pip",
        old_version="6.0.5",
        new_version="7.0.0",
    )
    mock_process.side_effect = MajorBumpPR(
        "major version bump on ipware", dep=dep, meta=meta
    )

    pr = MagicMock()
    pr.number = 42
    pr.title = "Bump ipware from 6.0.5 to 7.0.0"
    pr.user.login = "dependabot[bot]"
    pr.head.ref = "dependabot/pip/ipware-7.0.0"
    # Simulate existing verdict comment
    pr.get_issue_comments.return_value = [
        _gh_comment(body=Verdict.NO_VERDICT.comment("Manual review needed."))
    ]
    pr.get_reviews.return_value = []

    with patch("scripts.automerge_dependabot.Github") as gh_cls:
        gh_cls.return_value.get_repo.return_value.get_pulls.return_value = [pr]
        main()

    # No major_bumps output written
    output = output_file.read_text()
    assert "major_bumps=" not in output
