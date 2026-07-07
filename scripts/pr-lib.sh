#!/usr/bin/env bash
# Shared helpers for scripts that create commits, branches, and PRs via
# the GitHub API. Source this file; do not execute it.

# Require GH_TOKEN and REPO to be set, else exit 1.
require_token_repo() {
  if [ -z "${GH_TOKEN:-}" ] || [ -z "${REPO:-}" ]; then
    echo "Error: GH_TOKEN and REPO are required."
    exit 1
  fi
}

# Echo the commit message from .blender-commit-msg (removing the file
# afterward), or the provided default. Usage: read_commit_msg "default"
read_commit_msg() {
  if [ -f .blender-commit-msg ]; then
    cat .blender-commit-msg
    rm .blender-commit-msg
  else
    echo "$1"
  fi
}

# Return 0 when there are no staged or unstaged changes.
no_changes() {
  git diff --quiet && git diff --cached --quiet
}

# Echo the list of changed (unstaged) files, one per line.
list_changed_files() {
  git diff --name-only
}

# Echo a markdown link to the current Actions run, or a plain label.
run_link() {
  local server="${GITHUB_SERVER_URL:-https://github.com}"
  local repository="${GITHUB_REPOSITORY:-mozilla/blender}"
  local run_id="${GITHUB_RUN_ID:-}"
  if [ -n "$run_id" ]; then
    echo "[BLEnder investigation](${server}/${repository}/actions/runs/${run_id})"
  else
    echo "BLEnder investigation"
  fi
}

# Create a branch ref at SHA, updating it if it already exists.
# Usage: create_or_update_branch REPO BRANCH SHA
create_or_update_branch() {
  local repo="$1" branch="$2" sha="$3"
  gh api "repos/${repo}/git/refs" \
    --method POST \
    --field "ref=refs/heads/${branch}" \
    --field "sha=${sha}" || {
    echo "Branch ${branch} already exists. Updating."
    gh api "repos/${repo}/git/refs/heads/${branch}" \
      --method PATCH \
      --field "sha=${sha}"
  }
}

# Echo the number of an open PR for the given head branch, or empty.
# Usage: existing_open_pr REPO BRANCH
existing_open_pr() {
  gh pr list --repo "$1" --head "$2" --state open --json number --jq '.[0].number // empty'
}

# Echo the PR-body line describing a dependency bump. On public repos the
# alert link is omitted — it discloses the package, CVE, and severity
# before a fix is out. Usage: bump_alert_line REPO PACKAGE VERSION ALERT
bump_alert_line() {
  local repo="$1" package="$2" version="$3" alert="$4"
  local visibility
  visibility=$(gh api "repos/${repo}" --jq '.visibility')
  if [ "$visibility" = "public" ]; then
    echo "Resolves a flagged transitive dependency advisory."
  else
    echo "Bumps **${package}** to \`${version:-latest}\` to resolve [Dependabot alert #${alert}](https://github.com/${repo}/security/dependabot/${alert})."
  fi
}
