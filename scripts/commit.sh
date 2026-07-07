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
# shellcheck source=scripts/pr-lib.sh
source "${SCRIPT_DIR}/pr-lib.sh"

require_token_repo

# Read commit message from Claude, fall back to default
COMMIT_MSG=$(read_commit_msg "BLEnder fix: auto-fix CI failure from dependency update")

if no_changes; then
  echo "No changes to commit."
  echo "pushed=false" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

PARENT=$(git rev-parse HEAD)

# Collect changed files explicitly so we control what gets committed
CHANGED_FILES=()
while IFS= read -r file; do
  [ -z "$file" ] && continue
  CHANGED_FILES+=("$file")
done < <(list_changed_files)

COMMIT=$("${SCRIPT_DIR}/git-commit-api.sh" "$COMMIT_MSG" "$PARENT" "${CHANGED_FILES[@]}")

# Update branch ref
BRANCH=$(git rev-parse --abbrev-ref HEAD)
gh api "repos/${REPO}/git/refs/heads/${BRANCH}" \
  --method PATCH \
  --field "sha=${COMMIT}"

echo "Pushed verified commit ${COMMIT}"
echo "pushed=true" >> "${GITHUB_OUTPUT:-/dev/null}"
