#!/usr/bin/env bash
# BLEnder fork fix PR: commit Claude's fix to a branch on the private
# advisory fork and open a pull request there.
#
# Runs in the private fork checkout after Claude's fix process exits.
# The fork is private to advisory collaborators, so the PR and its body
# carry no public disclosure risk. Reads the commit message from
# .blender-commit-msg and delegates blob -> tree -> commit to
# git-commit-api.sh.
#
# Environment variables:
#   GH_TOKEN       -- GitHub token with contents+pull-requests write (required)
#   REPO           -- private fork repo, e.g. org/ghsa-xxxx-yyyy-zzzz (required)
#   ALERT_NUMBER   -- Dependabot alert number (required)
#   ALERT_PACKAGE  -- package name (required)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${GH_TOKEN:-}" ] || [ -z "${REPO:-}" ]; then
  echo "Error: GH_TOKEN and REPO are required."
  exit 1
fi

if [ -z "${ALERT_NUMBER:-}" ] || [ -z "${ALERT_PACKAGE:-}" ]; then
  echo "Error: ALERT_NUMBER and ALERT_PACKAGE are required."
  exit 1
fi

if git diff --quiet && git diff --cached --quiet; then
  echo "No changes to commit. Nothing to do."
  echo "pushed=false" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

# Read commit message from Claude, fall back to default
if [ -f .blender-commit-msg ]; then
  COMMIT_MSG=$(cat .blender-commit-msg)
  rm .blender-commit-msg
else
  COMMIT_MSG="BLEnder fix: security update for ${ALERT_PACKAGE}"
fi

BRANCH_NAME="blender/fix-alert-${ALERT_NUMBER}"

DEFAULT_BRANCH=$(gh api "repos/${REPO}" --jq '.default_branch')
PARENT=$(gh api "repos/${REPO}/git/ref/heads/${DEFAULT_BRANCH}" --jq '.object.sha')

# Collect changed files explicitly so we control what gets committed
CHANGED_FILES=()
while IFS= read -r file; do
  [ -z "$file" ] && continue
  CHANGED_FILES+=("$file")
done < <(git diff --name-only)

COMMIT_SHA=$("${SCRIPT_DIR}/git-commit-api.sh" "$COMMIT_MSG" "$PARENT" "${CHANGED_FILES[@]}")

# Create branch ref, updating it if it already exists
gh api "repos/${REPO}/git/refs" \
  --method POST \
  --field "ref=refs/heads/${BRANCH_NAME}" \
  --field "sha=${COMMIT_SHA}" || {
    echo "Branch ${BRANCH_NAME} already exists. Updating."
    gh api "repos/${REPO}/git/refs/heads/${BRANCH_NAME}" \
      --method PATCH \
      --field "sha=${COMMIT_SHA}"
  }

echo "Created branch ${BRANCH_NAME} with commit ${COMMIT_SHA}"

# Skip PR creation if one is already open for this branch
EXISTING_PR=$(gh pr list --repo "$REPO" --head "$BRANCH_NAME" --state open --json number --jq '.[0].number // empty')
if [ -n "$EXISTING_PR" ]; then
  echo "PR #${EXISTING_PR} already open for ${BRANCH_NAME}. Skipping."
  echo "pushed=true" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

# Build PR body. The fork is private, so include the verdict context.
SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"
REPOSITORY="${GITHUB_REPOSITORY:-mozilla/blender}"
RUN_ID="${GITHUB_RUN_ID:-}"
if [ -n "$RUN_ID" ]; then
  RUN_LINK="[BLEnder investigation](${SERVER_URL}/${REPOSITORY}/actions/runs/${RUN_ID})"
else
  RUN_LINK="BLEnder investigation"
fi

VERDICT_SECTION=""
if [ -f .blender-alert-verdict.json ]; then
  REASON=$(jq -r '.reason // ""' .blender-alert-verdict.json)
  PATHS=$(jq -r '(.vulnerable_paths // []) | map("- `" + . + "`") | join("\n")' .blender-alert-verdict.json)
  VERDICT_SECTION="

## Investigation verdict

${REASON}"
  if [ -n "$PATHS" ]; then
    VERDICT_SECTION="${VERDICT_SECTION}

### Vulnerable paths

${PATHS}"
  fi
fi

PR_BODY="## Summary

Security fix for **${ALERT_PACKAGE}** (Dependabot alert #${ALERT_NUMBER}).
Prepared on the private advisory fork for review before publication.${VERDICT_SECTION}

---
*Created by ${RUN_LINK} via [BLEnder](https://github.com/mozilla/blender)*"

PR_TITLE="Security fix: ${ALERT_PACKAGE} (alert #${ALERT_NUMBER})"

gh pr create \
  --repo "$REPO" \
  --head "$BRANCH_NAME" \
  --base "$DEFAULT_BRANCH" \
  --title "$PR_TITLE" \
  --body "$PR_BODY"

echo "PR created."
echo "pushed=true" >> "${GITHUB_OUTPUT:-/dev/null}"
