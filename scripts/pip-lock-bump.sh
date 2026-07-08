#!/usr/bin/env bash
# BLEnder pip lock bump: upgrade a transitive pip dependency via the
# repo's lock tool, commit changed lock files via verified commit,
# and open a PR.
#
# Runs after the lock tool upgrade in the target repo checkout.
# Delegates blob -> tree -> commit to git-commit-api.sh.
#
# Environment variables:
#   GH_TOKEN          -- GitHub token (required, also used for gh cli)
#   PACKAGE           -- pip package name (required)
#   PATCHED_VERSION   -- version to bump to (required)
#   ALERT_NUMBER      -- Dependabot alert number (required)
#   REPO              -- target repo, e.g. mozilla/fx-private-relay (required)
#   PIP_LOCK_TOOL     -- lock tool name: uv, poetry, or pipenv (required)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/pr-lib.sh
source "${SCRIPT_DIR}/pr-lib.sh"

require_token_repo

if [ -z "${PACKAGE:-}" ] || [ -z "${ALERT_NUMBER:-}" ]; then
  echo "Error: PACKAGE and ALERT_NUMBER are required."
  exit 1
fi

if [ -z "${PIP_LOCK_TOOL:-}" ]; then
  echo "Error: PIP_LOCK_TOOL is required."
  exit 1
fi

# Determine which lock files to check based on tool
case "$PIP_LOCK_TOOL" in
  uv)      LOCK_FILES=("uv.lock") ;;
  poetry)  LOCK_FILES=("poetry.lock") ;;
  pipenv)  LOCK_FILES=("Pipfile.lock") ;;
  *)
    echo "Unknown pip lock tool: ${PIP_LOCK_TOOL}"
    exit 1
    ;;
esac

# Check that at least one lock file changed
CHANGED_FILES=()
for file in "${LOCK_FILES[@]}"; do
  if ! git diff --quiet "$file" 2>/dev/null; then
    CHANGED_FILES+=("$file")
  fi
done

if [ ${#CHANGED_FILES[@]} -eq 0 ]; then
  echo "No lock files changed after ${PIP_LOCK_TOOL} upgrade. Nothing to do."
  exit 0
fi

BRANCH_NAME="blender/security-bump-${PACKAGE}"

# Check for existing open PR on this branch
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

COMMIT_SHA=$("${SCRIPT_DIR}/git-commit-api.sh" "$COMMIT_MSG" "$PARENT" "${CHANGED_FILES[@]}")

# Create branch ref
create_or_update_branch "$REPO" "$BRANCH_NAME" "$COMMIT_SHA"

echo "Created branch ${BRANCH_NAME} with commit ${COMMIT_SHA}"

# Build PR body
RUN_LINK=$(run_link)
ALERT_LINE=$(bump_alert_line "$REPO" "$PACKAGE" "${PATCHED_VERSION:-}" "$ALERT_NUMBER")

PR_BODY="## Summary

${ALERT_LINE}

This is a transitive dependency update via \`${PIP_LOCK_TOOL}\`. Only lock files changed.

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
