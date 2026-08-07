#!/usr/bin/env bash
# BLEnder yarn bump: commit yarn.lock (+ package.json) changes via a verified
# commit and open a PR. Runs after scripts/yarn-fix.sh in the target checkout.
#
# Mirrors npm-bump.sh; delegates blob -> tree -> commit to git-commit-api.sh.
# See #122.
#
# Environment variables:
#   GH_TOKEN          -- GitHub token (required, also used by gh cli)
#   PACKAGE           -- yarn package name (required)
#   PATCHED_VERSION   -- version to bump to (optional)
#   ALERT_NUMBER      -- Dependabot alert number (required)
#   REPO              -- target repo, e.g. mozilla/fxa (required)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/pr-lib.sh
source "${SCRIPT_DIR}/pr-lib.sh"

require_token_repo

if [ -z "${PACKAGE:-}" ] || [ -z "${ALERT_NUMBER:-}" ]; then
  echo "Error: PACKAGE and ALERT_NUMBER are required."
  exit 1
fi

# Check that yarn.lock changed
if git diff --quiet yarn.lock 2>/dev/null; then
  echo "yarn.lock unchanged after yarn up. Nothing to do."
  exit 0
fi

BRANCH_NAME="blender/security-bump-${PACKAGE}"

# Check for existing open PR on this branch — exit before any API calls
EXISTING_PR=$(existing_open_pr "$REPO" "$BRANCH_NAME")
if [ -n "$EXISTING_PR" ]; then
  echo "PR #${EXISTING_PR} already open for ${BRANCH_NAME}. Skipping."
  exit 0
fi

COMMIT_MSG="chore(deps): bump ${PACKAGE} to ${PATCHED_VERSION:-latest}

Resolves Dependabot alert #${ALERT_NUMBER}.
Created by BLEnder (https://github.com/mozilla/blender)"

DEFAULT_BRANCH=$(gh api "repos/${REPO}" --jq '.default_branch')
PARENT=$(gh api "repos/${REPO}/git/ref/heads/${DEFAULT_BRANCH}" --jq '.object.sha')

# Collect changed files. NOTE: PnP repos may also change .pnp.cjs and
# .yarn/cache/* — not handled here yet (see #122).
CHANGED_FILES=()
for file in yarn.lock package.json; do
  if ! git diff --quiet "$file" 2>/dev/null; then
    CHANGED_FILES+=("$file")
  fi
done

COMMIT_SHA=$("${SCRIPT_DIR}/git-commit-api.sh" "$COMMIT_MSG" "$PARENT" "${CHANGED_FILES[@]}")

# Create branch ref
create_or_update_branch "$REPO" "$BRANCH_NAME" "$COMMIT_SHA"

echo "Created branch ${BRANCH_NAME} with commit ${COMMIT_SHA}"

# Build PR body
RUN_LINK=$(run_link)
ALERT_LINE=$(bump_alert_line "$REPO" "$PACKAGE" "${PATCHED_VERSION:-}" "$ALERT_NUMBER")

PR_BODY="## Summary

${ALERT_LINE}

This is a transitive dependency update. Only \`yarn.lock\` (and possibly \`package.json\`) changed.

---
*Created by ${RUN_LINK} via [BLEnder](https://github.com/mozilla/blender)*"

PR_TITLE="chore(deps): bump ${PACKAGE} to ${PATCHED_VERSION:-latest}"

gh pr create \
  --repo "$REPO" \
  --head "$BRANCH_NAME" \
  --base "$DEFAULT_BRANCH" \
  --title "$PR_TITLE" \
  --body "$PR_BODY"

echo "PR created."
