#!/usr/bin/env bash
# BLEnder shared helper: create a verified commit via the GitHub API.
#
# Uploads changed files as blobs, builds a tree, and creates a commit
# signed by github-actions[bot]. Prints the new commit SHA to stdout.
#
# Usage:
#   scripts/git-commit-api.sh <commit_msg> <parent_sha> [file1 file2 ...]
#
# If no files are passed, reads changed files from `git diff --name-only`.
#
# Environment variables:
#   GH_TOKEN  -- GitHub token with contents:write (required)
#   REPO      -- GitHub repo, e.g. mozilla/fx-private-relay (required)

set -euo pipefail

if [ -z "${GH_TOKEN:-}" ] || [ -z "${REPO:-}" ]; then
  echo "Error: GH_TOKEN and REPO are required." >&2
  exit 1
fi

COMMIT_MSG="${1:?commit message required}"
PARENT="${2:?parent SHA required}"
shift 2

# Collect files: positional args or git diff
FILES=("$@")
if [ ${#FILES[@]} -eq 0 ]; then
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    FILES+=("$f")
  done < <(git diff --name-only)
fi

if [ ${#FILES[@]} -eq 0 ]; then
  echo "No changed files." >&2
  exit 1
fi

BASE_TREE=$(gh api "repos/${REPO}/git/commits/${PARENT}" --jq '.tree.sha')

# Upload each file as a blob
TREE_ITEMS="[]"
for file in "${FILES[@]}"; do
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

echo "$COMMIT_SHA"
