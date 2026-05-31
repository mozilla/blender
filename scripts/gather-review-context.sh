#!/usr/bin/env bash
# BLEnder gather-review-context: fetch review comments + plan, build prompt.
#
# Shared script used when addressing plan feedback or code review feedback.
# Only includes comments from trusted author associations and unresolved
# review threads.
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
#   TRUSTED_AUTHOR_ASSOCIATIONS -- Comma-separated list of trusted associations (default: OWNER)

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

ISSUE_NUMBER="${ISSUE_NUMBER:-0}"
TRUSTED="${TRUSTED_AUTHOR_ASSOCIATIONS:-OWNER}"
echo "BLEnder gather-review-context: PR #${PR_NUMBER} issue #${ISSUE_NUMBER} repo=${REPO}"
echo "  Trusted associations: ${TRUSTED}"

# Build jq filter for trusted author_association values
TRUST_FILTER=$(echo "$TRUSTED" | tr ',' '\n' | sed 's/^ *//;s/ *$//' | jq -R -s 'split("\n") | map(select(. != ""))')

# Split REPO into owner/name for GraphQL
REPO_OWNER="${REPO%%/*}"
REPO_NAME="${REPO##*/}"

# --- Read plan file (BLEnder-authored, no sanitization needed) ---
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

# --- Fetch PR review comments (trusted authors, unresolved only) ---
echo "Fetching review comments on PR #${PR_NUMBER} (trusted + unresolved)..."
review_comments=""

# Issue comments (general PR comments) — trusted authors only
issue_comments=$(gh api "repos/${REPO}/issues/${PR_NUMBER}/comments" --paginate \
  --jq ".[] | select(.user.login | endswith(\"[bot]\") | not) | select(.author_association as \$a | ${TRUST_FILTER} | index(\$a)) | \"### Comment by \(.user.login) [\(.html_url)]\n\(.body)\n\"" \
  2>/dev/null || echo "")

# PR review comments via GraphQL — unresolved threads, trusted authors
# shellcheck disable=SC2016  # $owner/$name/$number are GraphQL variables, not shell
pr_review_comments=$(gh api graphql -f query='
  query($owner: String!, $name: String!, $number: Int!) {
    repository(owner: $owner, name: $name) {
      pullRequest(number: $number) {
        reviewThreads(first: 100) {
          nodes {
            isResolved
            comments(first: 10) {
              nodes {
                author { login }
                authorAssociation
                body
                url
                path
                line
              }
            }
          }
        }
      }
    }
  }
' -f owner="$REPO_OWNER" -f name="$REPO_NAME" -F number="$PR_NUMBER" \
  --jq ".data.repository.pullRequest.reviewThreads.nodes[]
    | select(.isResolved == false)
    | .comments.nodes[]
    | select(.author.login | endswith(\"[bot]\") | not)
    | select(.authorAssociation as \$a | ${TRUST_FILTER} | index(\$a))
    | \"### Review comment by \(.author.login) on \(.path // \"general\"):\(.line // \"\") [\(.url)]\n\(.body)\n\"" \
  2>/dev/null || echo "")

# PR reviews with body — trusted authors only
pr_reviews=$(gh api "repos/${REPO}/pulls/${PR_NUMBER}/reviews" --paginate \
  --jq ".[] | select(.body != \"\" and .body != null) | select(.user.login | endswith(\"[bot]\") | not) | select(.author_association as \$a | ${TRUST_FILTER} | index(\$a)) | \"### Review by \(.user.login) (\(.state)) [\(.html_url)]\n\(.body)\n\"" \
  2>/dev/null || echo "")

review_comments="${issue_comments}${pr_review_comments}${pr_reviews}"

if [ -z "$review_comments" ]; then
  review_comments="(no review comments found from trusted reviewers)"
fi

# --- Build the prompt ---
echo "Building prompt from ${PROMPT_TEMPLATE}..."
prompt=$(cat "$PROMPT_TEMPLATE")

# Neutralize template markers in API-fetched content to prevent
# cross-placeholder injection (e.g., issue title containing "{{PLAN_CONTENT}}")
issue_title="${issue_title//\{\{/\{_\{}"
issue_body="${issue_body//\{\{/\{_\{}"
review_comments="${review_comments//\{\{/\{_\{}"

prompt="${prompt//\{\{ISSUE_NUMBER\}\}/$ISSUE_NUMBER}"
prompt="${prompt//\{\{ISSUE_TITLE\}\}/$issue_title}"
prompt="${prompt//\{\{ISSUE_BODY\}\}/$issue_body}"
prompt="${prompt//\{\{PLAN_CONTENT\}\}/$plan_content}"
prompt="${prompt//\{\{REVIEW_COMMENTS\}\}/$review_comments}"
prompt="${prompt//\{\{ISSUE_COMMENTS\}\}/$review_comments}"
prompt="${prompt//\{\{REPO_TREE\}\}/}"

# Write prompt to file for run-claude.sh
printf '%s\n' "$prompt" > .blender-prompt
echo "Prompt written to .blender-prompt"
