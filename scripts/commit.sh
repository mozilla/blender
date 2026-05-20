#!/usr/bin/env bash
# BLEnder commit: create a verified commit via the GitHub API.
#
# Runs after Claude's process exits. Reads commit message from .blender-commit-msg.
# Delegates blob -> tree -> commit to git-commit-api.sh, then updates the
# branch ref.
#
# Environment variables:
#   GH_TOKEN  -- GitHub token with contents:write (required)
#   REPO      -- GitHub repo, e.g. mozilla/fx-private-relay (required)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
  echo "pushed=false" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

PARENT=$(git rev-parse HEAD)

COMMIT=$("${SCRIPT_DIR}/git-commit-api.sh" "$COMMIT_MSG" "$PARENT")

# Update branch ref
BRANCH=$(git rev-parse --abbrev-ref HEAD)
gh api "repos/${REPO}/git/refs/heads/${BRANCH}" \
  --method PATCH \
  --field "sha=${COMMIT}"

echo "Pushed verified commit ${COMMIT}"
echo "pushed=true" >> "${GITHUB_OUTPUT:-/dev/null}"
