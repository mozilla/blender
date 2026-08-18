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

# Commit a dependency bump (lockfile + package.json) via a verified commit and
# open a PR. npm-bump.sh and yarn-bump.sh differ only in which lockfile they
# touch, so both call this. Usage: open_bump_pr LOCKFILE
#   env: GH_TOKEN, PACKAGE, PATCHED_VERSION, ALERT_NUMBER, REPO
open_bump_pr() {
  local lockfile="$1"
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  require_token_repo

  if [ -z "${PACKAGE:-}" ] || [ -z "${ALERT_NUMBER:-}" ]; then
    echo "Error: PACKAGE and ALERT_NUMBER are required."
    exit 1
  fi

  if git diff --quiet "$lockfile" 2>/dev/null; then
    echo "${lockfile} unchanged after fix. Nothing to do."
    exit 0
  fi

  local branch="blender/security-bump-${PACKAGE}"

  local existing
  existing=$(existing_open_pr "$REPO" "$branch")
  if [ -n "$existing" ]; then
    echo "PR #${existing} already open for ${branch}. Skipping."
    exit 0
  fi

  local commit_msg="chore(deps): bump ${PACKAGE} to ${PATCHED_VERSION:-latest}

Resolves Dependabot alert #${ALERT_NUMBER}.
Created by BLEnder (https://github.com/mozilla/blender)"

  local default_branch parent
  default_branch=$(gh api "repos/${REPO}" --jq '.default_branch')
  parent=$(gh api "repos/${REPO}/git/ref/heads/${default_branch}" --jq '.object.sha')

  local changed_files=() file
  for file in "$lockfile" package.json; do
    if ! git diff --quiet "$file" 2>/dev/null; then
      changed_files+=("$file")
    fi
  done

  local commit_sha
  commit_sha=$("${script_dir}/git-commit-api.sh" "$commit_msg" "$parent" "${changed_files[@]}")

  create_or_update_branch "$REPO" "$branch" "$commit_sha"
  echo "Created branch ${branch} with commit ${commit_sha}"

  local run_link_md alert_line
  run_link_md=$(run_link)
  alert_line=$(bump_alert_line "$REPO" "$PACKAGE" "${PATCHED_VERSION:-}" "$ALERT_NUMBER")

  local pr_body="## Summary

${alert_line}

This is a transitive dependency update. Only \`${lockfile}\` (and possibly \`package.json\`) changed.

---
*Created by ${run_link_md} via [BLEnder](https://github.com/mozilla/blender)*"

  gh pr create \
    --repo "$REPO" \
    --head "$branch" \
    --base "$default_branch" \
    --title "chore(deps): bump ${PACKAGE} to ${PATCHED_VERSION:-latest}" \
    --body "$pr_body"

  echo "PR created."
}
