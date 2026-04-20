#!/usr/bin/env bash
# BLEnder commit: create a verified commit via the GitHub API.
#
# Runs after Claude's process exits. Reads commit message from .blender-commit-msg.
# Uses blob -> tree -> commit -> ref-update to produce a verified commit
# signed by github-actions[bot].
#
# Environment variables:
#   GH_TOKEN  -- GitHub token with contents:write (required)
#   REPO      -- GitHub repo, e.g. mozilla/fx-private-relay (required)

set -euo pipefail

if [ -z "${GH_TOKEN:-}" ] || [ -z "${REPO:-}" ]; then
  echo "Error: GH_TOKEN and REPO are required."
  exit 1
fi

# Read commit message from Claude, fall back to default
if [ -f .blender-commit-msg ]; then
  COMMIT_MSG=$(cat .blender-commit-msg)
  rm .blender-commit-msg
else
  COMMIT_MSG="BLEnder fix: auto-fix CI failure from dependency update"
fi

if git diff --quiet && git diff --cached --quiet; then
  echo "No changes to commit."
  exit 0
fi

PARENT=$(git rev-parse HEAD)
BASE_TREE=$(gh api "repos/${REPO}/git/commits/${PARENT}" --jq '.tree.sha')

# Upload each changed file as a blob
TREE_ITEMS="[]"
while IFS= read -r file; do
  [ -z "$file" ] && continue
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
done < <(git diff --name-only)

# Create tree from blobs
TREE_SHA=$(jq -n \
  --arg base "$BASE_TREE" \
  --argjson tree "$TREE_ITEMS" \
  '{"base_tree": $base, "tree": $tree}' | \
  gh api "repos/${REPO}/git/trees" \
    --method POST \
    --input - \
    --jq '.sha')

# Create verified commit
COMMIT=$(gh api "repos/${REPO}/git/commits" \
  --method POST \
  --field "message=${COMMIT_MSG}" \
  --field "tree=${TREE_SHA}" \
  --field "parents[]=${PARENT}" \
  --jq '.sha')

# Update branch ref
BRANCH=$(git rev-parse --abbrev-ref HEAD)
gh api "repos/${REPO}/git/refs/heads/${BRANCH}" \
  --method PATCH \
  --field "sha=${COMMIT}"

echo "Pushed verified commit ${COMMIT}"
