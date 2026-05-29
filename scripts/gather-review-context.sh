#!/usr/bin/env bash
# BLEnder gather-review-context: fetch review comments + plan, build prompt.
#
# Shared script used when addressing plan feedback or code review feedback.
# Appends review comments to the appropriate prompt template.
#
# This script has GH_TOKEN but does NOT have ANTHROPIC_API_KEY.
# It writes the final prompt to .blender-prompt for run-claude.sh.
#
# Environment variables:
#   PR_NUMBER          -- PR number (required)
#   ISSUE_NUMBER       -- Issue number (required)
#   REPO               -- GitHub repo, e.g. mozilla/fx-private-relay (required)
#   GH_TOKEN           -- GitHub token for API calls (required)
#   PROMPT_TEMPLATE    -- Path to prompt template file (required)
#   ISSUE_TITLE        -- Issue title (optional)

set -euo pipefail

if [ -z "${PR_NUMBER:-}" ] || [ -z "${REPO:-}" ]; then
  echo "Error: PR_NUMBER and REPO are required."
  exit 1
fi

if [ -z "${GH_TOKEN:-}" ]; then
  echo "Error: GH_TOKEN is required."
  exit 1
fi

if [ -z "${PROMPT_TEMPLATE:-}" ]; then
  echo "Error: PROMPT_TEMPLATE is required."
  exit 1
fi

if [ ! -f "$PROMPT_TEMPLATE" ]; then
  echo "Error: Prompt template not found: $PROMPT_TEMPLATE"
  exit 1
fi

# --- Sanitize untrusted input before inserting into prompts ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/sanitize.sh
source "${SCRIPT_DIR}/sanitize.sh"

ISSUE_NUMBER="${ISSUE_NUMBER:-0}"
echo "BLEnder gather-review-context: PR #${PR_NUMBER} issue #${ISSUE_NUMBER} repo=${REPO}"

# --- Read plan file ---
plan_file=".blender/plans/${ISSUE_NUMBER}.md"
plan_content=""
if [ -f "$plan_file" ]; then
  echo "Reading plan from ${plan_file}..."
  plan_content=$(cat "$plan_file")
fi

# --- Fetch issue body ---
issue_body=""
issue_title="${ISSUE_TITLE:-}"
if [ "$ISSUE_NUMBER" != "0" ]; then
  echo "Fetching issue #${ISSUE_NUMBER}..."
  issue_json=$(gh api "repos/${REPO}/issues/${ISSUE_NUMBER}")
  issue_title=$(echo "$issue_json" | jq -r '.title // ""')
  issue_body=$(echo "$issue_json" | jq -r '.body // "(no body)"')
fi

# --- Fetch PR review comments ---
echo "Fetching review comments on PR #${PR_NUMBER}..."
review_comments=""

# Issue comments (general PR comments)
issue_comments=$(gh api "repos/${REPO}/issues/${PR_NUMBER}/comments" --paginate \
  --jq '.[] | select(.user.login | endswith("[bot]") | not) | "### Comment by \(.user.login)\n\(.body)\n"' \
  2>/dev/null || echo "")

# PR review comments (inline code comments)
pr_review_comments=$(gh api "repos/${REPO}/pulls/${PR_NUMBER}/comments" --paginate \
  --jq '.[] | "### Review comment by \(.user.login) on \(.path):\(.line // .original_line)\n\(.body)\n"' \
  2>/dev/null || echo "")

# PR reviews with body
pr_reviews=$(gh api "repos/${REPO}/pulls/${PR_NUMBER}/reviews" --paginate \
  --jq '.[] | select(.body != "" and .body != null) | "### Review by \(.user.login) (\(.state))\n\(.body)\n"' \
  2>/dev/null || echo "")

review_comments="${issue_comments}${pr_review_comments}${pr_reviews}"

if [ -z "$review_comments" ]; then
  review_comments="(no review comments found)"
fi

# --- Build the prompt ---
echo "Building prompt from ${PROMPT_TEMPLATE}..."
prompt=$(cat "$PROMPT_TEMPLATE")

safe_title=$(sanitize_for_prompt "$issue_title")
safe_body=$(sanitize_for_prompt "$issue_body")
safe_plan=$(sanitize_for_prompt "$plan_content")
safe_reviews=$(sanitize_for_prompt "$review_comments")

prompt="${prompt//\{\{ISSUE_NUMBER\}\}/$ISSUE_NUMBER}"
prompt="${prompt//\{\{ISSUE_TITLE\}\}/$safe_title}"
prompt="${prompt//\{\{ISSUE_BODY\}\}/$safe_body}"
prompt="${prompt//\{\{PLAN_CONTENT\}\}/$safe_plan}"
prompt="${prompt//\{\{REVIEW_COMMENTS\}\}/$safe_reviews}"
prompt="${prompt//\{\{ISSUE_COMMENTS\}\}/$safe_reviews}"
prompt="${prompt//\{\{REPO_TREE\}\}/}"

# Write prompt to file for run-claude.sh
echo "$prompt" > .blender-prompt
echo "Prompt written to .blender-prompt"
