#!/usr/bin/env bash
# BLEnder npm bump: commit package-lock.json changes via verified commit
# and open a PR.
#
# Runs after `npm update <package>` in the target repo checkout.
# Uses blob -> tree -> commit -> ref pattern from commit.sh.
#
# Environment variables:
#   GH_TOKEN          -- GitHub token (required, also used as GH_TOKEN for gh cli)
#   PACKAGE           -- npm package name (required)
#   PATCHED_VERSION   -- version to bump to (required)
#   ALERT_NUMBER      -- Dependabot alert number (required)
#   REPO              -- target repo, e.g. mozilla/blurts-server (required)

set -euo pipefail

if [ -z "${GH_TOKEN:-}" ] || [ -z "${REPO:-}" ]; then
  echo "Error: GH_TOKEN and REPO are required."
  exit 1
fi

if [ -z "${PACKAGE:-}" ] || [ -z "${ALERT_NUMBER:-}" ]; then
  echo "Error: PACKAGE and ALERT_NUMBER are required."
  exit 1
fi

# Check that package-lock.json changed
if git diff --quiet package-lock.json 2>/dev/null; then
  echo "package-lock.json unchanged after npm update. Nothing to do."
  exit 0
fi

BRANCH_NAME="blender/security-bump-${PACKAGE}"
COMMIT_MSG="chore(deps): bump ${PACKAGE} to ${PATCHED_VERSION:-latest}

Resolves Dependabot alert #${ALERT_NUMBER}.
Created by BLEnder (https://github.com/mozilla/blender)"

DEFAULT_BRANCH=$(gh api "repos/${REPO}" --jq '.default_branch')
PARENT=$(gh api "repos/${REPO}/git/ref/heads/${DEFAULT_BRANCH}" --jq '.object.sha')
BASE_TREE=$(gh api "repos/${REPO}/git/commits/${PARENT}" --jq '.tree.sha')

# Upload changed files as blobs (package-lock.json, possibly package.json)
TREE_ITEMS="[]"
for file in package-lock.json package.json; do
  if ! git diff --quiet "$file" 2>/dev/null; then
    echo "Uploading ${file} ..."
    BLOB_SHA=$(base64 -w 0 "$file" | \
      jq -Rs '{"encoding": "base64", "content": .}' | \
      gh api "repos/${REPO}/git/blobs" \
      --method POST \
      --input - \
      --jq '.sha')
    TREE_ITEMS=$(echo "$TREE_ITEMS" | jq \
      --arg path "$file" \
      --arg sha "$BLOB_SHA" \
      '. + [{"path": $path, "mode": "100644", "type": "blob", "sha": $sha}]')
  fi
done

# Create tree
TREE_SHA=$(jq -n \
  --arg base "$BASE_TREE" \
  --argjson tree "$TREE_ITEMS" \
  '{"base_tree": $base, "tree": $tree}' | \
  gh api "repos/${REPO}/git/trees" \
    --method POST \
    --input - \
    --jq '.sha')

# Create verified commit
COMMIT_SHA=$(gh api "repos/${REPO}/git/commits" \
  --method POST \
  --field "message=${COMMIT_MSG}" \
  --field "tree=${TREE_SHA}" \
  --field "parents[]=${PARENT}" \
  --jq '.sha')

# Create branch ref
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

# Build PR body
SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"
REPOSITORY="${GITHUB_REPOSITORY:-mozilla/blender}"
RUN_ID="${GITHUB_RUN_ID:-}"
if [ -n "$RUN_ID" ]; then
  RUN_LINK="[BLEnder investigation](${SERVER_URL}/${REPOSITORY}/actions/runs/${RUN_ID})"
else
  RUN_LINK="BLEnder investigation"
fi

PR_BODY="## Summary

Bumps **${PACKAGE}** to \`${PATCHED_VERSION:-latest}\` to resolve [Dependabot alert #${ALERT_NUMBER}](https://github.com/${REPO}/security/dependabot/${ALERT_NUMBER}).

This is a transitive dependency update. Only \`package-lock.json\` (and possibly \`package.json\`) changed.

---
*Created by ${RUN_LINK} via [BLEnder](https://github.com/mozilla/blender)*"

PR_TITLE="chore(deps): bump ${PACKAGE} to ${PATCHED_VERSION:-latest}"

# Check for existing open PR on this branch
EXISTING_PR=$(gh pr list --repo "$REPO" --head "$BRANCH_NAME" --state open --json number --jq '.[0].number // empty')
if [ -n "$EXISTING_PR" ]; then
  echo "PR #${EXISTING_PR} already open for ${BRANCH_NAME}. Skipping."
  exit 0
fi

gh pr create \
  --repo "$REPO" \
  --head "$BRANCH_NAME" \
  --base "$DEFAULT_BRANCH" \
  --title "$PR_TITLE" \
  --body "$PR_BODY"

echo "PR created."
