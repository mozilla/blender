#!/usr/bin/env bash
# BLEnder gather-issue-context: fetch issue metadata, build plan prompt.
#
# This script has GH_TOKEN but does NOT have ANTHROPIC_API_KEY.
# It writes the final prompt to .blender-prompt for run-claude.sh.
# Only includes comments from trusted author associations.
#
# Environment variables:
#   ISSUE_NUMBER       -- Issue number (0 = let Claude pick) (required)
#   REPO               -- GitHub repo, e.g. mozilla/fx-private-relay (required)
#   GH_TOKEN           -- GitHub token for API calls (required)
#   PROMPT_TEMPLATE    -- Path to prompt template file (required)
#   ISSUE_TITLE        -- Issue title (optional, for fallback)
#   TRUSTED_AUTHOR_ASSOCIATIONS -- Comma-separated list of trusted associations (default: OWNER)

set -euo pipefail

if [ -z "${REPO:-}" ]; then
  echo "Error: REPO is required."
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
echo "BLEnder gather-issue-context: issue #${ISSUE_NUMBER} repo=${REPO}"

# Build jq filter for trusted author_association values
TRUST_FILTER=$(echo "$TRUSTED" | tr ',' '\n' | sed 's/^ *//;s/ *$//' | jq -R -s 'split("\n") | map(select(. != ""))')

# --- Fetch issue details ---
issue_body=""
issue_title="${ISSUE_TITLE:-}"
issue_comments=""

if [ "$ISSUE_NUMBER" != "0" ]; then
  echo "Fetching issue #${ISSUE_NUMBER}..."
  issue_json=$(gh api "repos/${REPO}/issues/${ISSUE_NUMBER}")
  issue_title=$(echo "$issue_json" | jq -r '.title // ""')
  issue_body=$(echo "$issue_json" | jq -r '.body // "(no body)"')

  echo "Fetching issue comments (trusted authors only)..."
  issue_comments=$(gh api "repos/${REPO}/issues/${ISSUE_NUMBER}/comments" --paginate \
    --jq ".[] | select(.user.login | endswith(\"[bot]\") | not) | select(.author_association as \$a | ${TRUST_FILTER} | index(\$a)) | \"### Comment by \(.user.login)\n\(.body)\n\"")
else
  echo "No specific issue — fetching all open issues for Claude to pick..."
  issues_json=$(gh api "repos/${REPO}/issues?state=open&per_page=50" \
    --jq '.[] | select(.pull_request == null) | "- #\(.number): \(.title) [labels: \([.labels[].name] | join(", "))]"')
  issue_body="Pick the most impactful issue from this list and create a plan for it:\n\n${issues_json}"
  issue_title="(Claude picks from open issues)"
fi

echo "  Title: ${issue_title}"

# --- Gather repo structure ---
echo "Gathering repo structure..."
repo_tree=$(tree -L 3 --noreport -I 'node_modules|.git|__pycache__|.tox|.mypy_cache|dist|build|*.egg-info' 2>/dev/null || echo "(tree not available)")

# --- Read agents.md if it exists ---
if [ -f .blender/agents.md ]; then
  echo "Reading .blender/agents.md..."
  issue_body="${issue_body}

## Repo context (.blender/agents.md)

$(cat .blender/agents.md)"
fi

# --- Build the prompt ---
echo "Building prompt from ${PROMPT_TEMPLATE}..."
prompt=$(cat "$PROMPT_TEMPLATE")

# Neutralize template markers in API-fetched content to prevent
# cross-placeholder injection (e.g., issue title containing "{{PLAN_CONTENT}}")
issue_title="${issue_title//\{\{/\{_\{}"
issue_body="${issue_body//\{\{/\{_\{}"
issue_comments="${issue_comments//\{\{/\{_\{}"

prompt="${prompt//\{\{ISSUE_NUMBER\}\}/$ISSUE_NUMBER}"
prompt="${prompt//\{\{ISSUE_TITLE\}\}/$issue_title}"
prompt="${prompt//\{\{ISSUE_BODY\}\}/$issue_body}"
prompt="${prompt//\{\{ISSUE_COMMENTS\}\}/$issue_comments}"
prompt="${prompt//\{\{REPO_TREE\}\}/$repo_tree}"

# Write prompt to file for run-claude.sh
printf '%s\n' "$prompt" > .blender-prompt
echo "Prompt written to .blender-prompt"
