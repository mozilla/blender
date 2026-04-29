"""Tests for version_in_range and its helpers."""

from __future__ import annotations

import pytest

from scripts.automerge_dependabot import (
    _normalize_pep440_range,
    version_in_range,
)


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
